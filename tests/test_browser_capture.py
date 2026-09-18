import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cv.browser_capture import BrowserCapture


def test_frame_queue_drops_stale_frames_under_backpressure():
    """A slow consumer shouldn't make the capture buffer grow unboundedly -
    the queue is bounded and _push_frame drops the oldest frame rather than
    blocking, which is what keeps this near-live instead of falling behind.
    Feeds raw bytes through _push_frame directly (no real browser needed).
    """
    cv2 = pytest.importorskip("cv2")  # opencv-python is an optional CV extra
    import base64
    import queue

    import numpy as np

    cap = BrowserCapture.__new__(BrowserCapture)  # skip __init__'s dependency check
    cap._frame_queue = queue.Queue(maxsize=2)

    ok, encoded = cv2.imencode(".jpg", np.zeros((4, 4, 3), dtype=np.uint8))
    assert ok
    tiny_jpeg = encoded.tobytes()

    for _ in range(3):
        cap._push_frame(base64.b64encode(tiny_jpeg))

    assert cap._frame_queue.qsize() == 2  # never exceeds maxsize


def test_raises_clean_error_when_constructed_without_dependencies_stubbed_missing(monkeypatch):
    import src.cv.browser_capture as mod

    monkeypatch.setattr(mod, "sync_playwright", None)
    with pytest.raises(RuntimeError, match="playwright and opencv-python are required"):
        BrowserCapture("https://example.com")
