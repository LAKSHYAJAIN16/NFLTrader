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

    def _ocr_digits(self, crop):
        if crop is None:
            return ""
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        config_str = "--psm 7 -c tessedit_char_whitelist=0123456789:"
        return pytesseract.image_to_string(thresh, config=config_str).strip()

    def read_frame(self, frame, timestamp=None) -> GameState:
        """Extract a GameState from a single BGR frame (numpy array). Any field
        that can't be confidently read falls back to a safe default of 0/None,
        so callers should sanity-check with GameState.is_plausible()."""
        home_score = self._parse_int(self._ocr_digits(self._crop(frame, "home_score")))
        away_score = self._parse_int(self._ocr_digits(self._crop(frame, "away_score")))
        clock_text = self._ocr_digits(self._crop(frame, "clock"))
        quarter_text = self._ocr_digits(self._crop(frame, "quarter"))

        return GameState(
            home_score=home_score or 0,
            away_score=away_score or 0,
            quarter=self._parse_quarter(quarter_text),
            clock_seconds=self._parse_clock(clock_text),
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
