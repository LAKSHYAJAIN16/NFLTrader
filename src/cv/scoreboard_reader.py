"""Reads game state (score, quarter, clock) off a broadcast scoreboard graphic
using OpenCV for frame handling/preprocessing and Tesseract for OCR.

The scoreboard's on-screen position is network/broadcast-specific, so it must
be calibrated once per source via a region-of-interest (ROI) config - see
tools/save_sample_frame.py for a helper to grab a frame to measure pixel
coordinates from, and data/roi.json.example for the config shape.
"""

import json
import os
import re
import time

import config
from src.cv.game_state import GameState

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

_CLOCK_RE = re.compile(r"(\d{1,2}):(\d{2})")
_QUARTER_RE = re.compile(r"([1-4])(?:st|nd|rd|th)?|OT")
_DOWN_RE = re.compile(r"(1ST|2ND|3RD|4TH)", re.IGNORECASE)
_DISTANCE_RE = re.compile(r"&\s*(\d{1,2}|GOAL)", re.IGNORECASE)
_FIELD_POS_RE = re.compile(r"(OWN|OPP)\s*(\d{1,2})", re.IGNORECASE)
_DOWN_ORDINALS = {"1ST": 1, "2ND": 2, "3RD": 3, "4TH": 4}


class ScoreboardReader:
    def __init__(self, roi_config=None):
        if cv2 is None or pytesseract is None:
            raise RuntimeError(
                "opencv-python and pytesseract are required for CV features. "
                "Install with: pip install opencv-python pytesseract "
                "(and the Tesseract binary itself - see README)."
            )
        self.roi = roi_config or self._load_default_roi()

    @staticmethod
    def _load_default_roi():
        if os.path.exists(config.ROI_CONFIG_PATH):
            with open(config.ROI_CONFIG_PATH) as f:
                return json.load(f)
        return None

    def _crop(self, frame, region_key):
        if not self.roi or region_key not in self.roi:
            return None
        x, y, w, h = self.roi[region_key]
        return frame[y:y + h, x:x + w]

    def _ocr(self, crop, whitelist=None):
        if crop is None:
            return ""
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        config_str = "--psm 7"
        if whitelist:
            config_str += f" -c tessedit_char_whitelist={whitelist}"
        return pytesseract.image_to_string(thresh, config=config_str).strip()

    def _ocr_digits(self, crop):
        return self._ocr(crop, whitelist="0123456789:")

    def _read_possession(self, frame):
        """Compares brightness of two small marker ROIs (e.g. a lit triangle/dot
        next to the team on offense) - whichever is brighter has the ball. Needs
        `possession_home_marker`/`possession_away_marker` in the ROI config;
        returns None (unknown) if they're not configured or too close to call.
        """
        home_crop = self._crop(frame, "possession_home_marker")
        away_crop = self._crop(frame, "possession_away_marker")
        if home_crop is None or away_crop is None:
            return None
        home_brightness = cv2.cvtColor(home_crop, cv2.COLOR_BGR2GRAY).mean()
        away_brightness = cv2.cvtColor(away_crop, cv2.COLOR_BGR2GRAY).mean()
        if abs(home_brightness - away_brightness) < 15:
            return None
        return home_brightness > away_brightness

    def read_frame(self, frame, timestamp=None) -> GameState:
        """Extract a GameState from a single BGR frame (numpy array). Any field
        that can't be confidently read falls back to a safe default (score/quarter/
        clock) or None (down/distance/yard_line/possession), so callers should
        sanity-check with GameState.is_plausible()."""
        home_score = self._parse_int(self._ocr_digits(self._crop(frame, "home_score")))
        away_score = self._parse_int(self._ocr_digits(self._crop(frame, "away_score")))
        clock_text = self._ocr_digits(self._crop(frame, "clock"))
        quarter_text = self._ocr_digits(self._crop(frame, "quarter"))
        down_distance_text = self._ocr(self._crop(frame, "down_distance"))
        field_position_text = self._ocr(self._crop(frame, "field_position"))
        possession_home = self._read_possession(frame)

        down, distance = self._parse_down_distance(down_distance_text)
        yard_line = self._parse_yard_line(field_position_text)

        return GameState(
            home_score=home_score or 0,
            away_score=away_score or 0,
            quarter=self._parse_quarter(quarter_text),
            clock_seconds=self._parse_clock(clock_text),
            possession_home=possession_home,
            down=down,
            distance=distance,
            yard_line=yard_line,
            timestamp=timestamp,
        )

    def read_video(self, source, sample_interval_sec=5.0):
        """Generator yielding a plausible GameState roughly every
        `sample_interval_sec` seconds of video. `source` is a file path,
        RTSP URL, or anything else cv2.VideoCapture accepts.
        """
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video source: {source}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_interval = max(1, int(fps * sample_interval_sec))
        frame_idx = 0
        prev_state = None

        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_idx % frame_interval == 0:
                    ts = frame_idx / fps
                    state = self.read_frame(frame, timestamp=ts)
                    if state.is_plausible(prev_state):
                        prev_state = state
                        yield state
                frame_idx += 1
        finally:
            cap.release()

    def read_browser(self, url, sample_interval_sec=5.0, headless=True):
        """Same as read_video, but the source is a live webpage rather than a
        direct video file/URL - see src/cv/browser_capture.py."""
        import time

        from src.cv.browser_capture import BrowserCapture

        capture = BrowserCapture(url, headless=headless).start()
        prev_state = None
        last_read = 0.0
        try:
            for frame in capture.frames():
                now = time.monotonic()
                if now - last_read < sample_interval_sec:
                    continue
                last_read = now
                state = self.read_frame(frame, timestamp=now)
                if state.is_plausible(prev_state):
                    prev_state = state
                    yield state
        finally:
            capture.stop()

    @staticmethod
    def _parse_int(text):
        digits = re.sub(r"\D", "", text)
        return int(digits) if digits else None

    @staticmethod
    def _parse_clock(text):
        m = _CLOCK_RE.search(text)
        if not m:
            return 15 * 60
        minutes, seconds = int(m.group(1)), int(m.group(2))
        return minutes * 60 + seconds

    @staticmethod
    def _parse_quarter(text):
        if "OT" in text.upper():
            return 5
        m = _QUARTER_RE.search(text)
        return int(m.group(1)) if m and m.group(1) else 1

    @staticmethod
    def _parse_down_distance(text):
        """Parses a graphic like '3RD & 7' into (down=3, distance=7)."""
        down_match = _DOWN_RE.search(text)
        distance_match = _DISTANCE_RE.search(text)
        down = _DOWN_ORDINALS.get(down_match.group(1).upper()) if down_match else None
        distance = None
        if distance_match:
            raw = distance_match.group(1).upper()
            distance = 0 if raw == "GOAL" else int(raw)
        return down, distance

    @staticmethod
    def _parse_yard_line(text):
        """Parses a graphic like 'OWN 35' / 'OPP 22' into yards-to-go for the
        possessing team's end zone (0-100). Returns None if unparseable -
        broadcasts vary widely here and this is best-effort."""
        m = _FIELD_POS_RE.search(text)
        if not m:
            return None
        side, yard = m.group(1).upper(), int(m.group(2))
        return (100 - yard) if side == "OWN" else yard
