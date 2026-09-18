"""Drives a video source through any per-frame detector into a
TrajectoryTracker. Shared by ball_tracker.py (generic COCO YOLO, zero setup)
and roboflow_tracker.py (fine-tuned NFL models, needs an API key) - both
expose the same `.detect(frame, frame_idx) -> Detection` interface, so
either can be dropped in here.
"""


def watch_video(source, detector, tracker, sample_every_n_frames=1):
    """Generator yielding a PlayPrediction for every frame (or every Nth
    frame, to trade detection resolution for speed) that produces one.
    `source` is a video file path/URL for cv2.VideoCapture."""
    import cv2  # local import: only needed for this real-video path

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video source: {source}")

    frame_idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx % sample_every_n_frames == 0:
                detection = detector.detect(frame, frame_idx)
                prediction = tracker.update(detection)
                if prediction:
                    yield prediction
            frame_idx += 1
    finally:
        cap.release()


def watch_browser(url, detector, tracker, sample_every_n_frames=1, headless=True):
    """Same as watch_video, but the source is a live webpage rather than a
    direct video file/URL - for a stream site cv2.VideoCapture can't decode
    directly (see src/cv/browser_capture.py). Runs the capture for the
    lifetime of this generator and tears it down cleanly on exit/break.
    """
    from src.cv.browser_capture import BrowserCapture

    capture = BrowserCapture(url, headless=headless).start()
    frame_idx = 0
    try:
        for frame in capture.frames():
            if frame_idx % sample_every_n_frames == 0:
                detection = detector.detect(frame, frame_idx)
                prediction = tracker.update(detection)
                if prediction:
                    yield prediction
            frame_idx += 1
    finally:
        capture.stop()
