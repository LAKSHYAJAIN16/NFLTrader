"""Turns any website into a stream of CV-readable frames, via a real
(headless) Chromium browser and the Chrome DevTools Protocol's screencast -
the piece that makes "point this at a stream page" actually work, since
cv2.VideoCapture can't decode a JS-rendered video player embedded in a page.

Verified in this environment: playwright launches chromium, loads a real
page, and CDP Page.startScreencast pushes frames on repaint - see the
commit history for the direct test. NOT verified against an actual live
sports-stream page, which this project has no access to: a real streaming
site may require login/paywall interaction before the player renders (this
captures whatever is on screen, so it works past DRM that only blocks
direct <video> element scraping, but not past a login wall), and some sites
detect and block headless browsers outright. Use `headless=False` and log in
manually first if a site requires it.

On latency: the CDP screencast itself is fast (pushes a frame per repaint,
not polled) - the bigger lever for "make it faster" is running this close to
the stream's origin server (a cloud VM in the right region cuts the network
hop that dominates real end-to-end latency far more than local compute
would), not anything about this module's implementation.
"""

import base64
import queue
import threading

import numpy as np

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

try:
    import cv2
except ImportError:
    cv2 = None


class BrowserCapture:
    def __init__(self, url, width=1280, height=720, headless=True):
        if sync_playwright is None or cv2 is None:
            raise RuntimeError(
                "playwright and opencv-python are required for browser capture. Install with: "
                "pip install playwright opencv-python && playwright install chromium"
            )
        self.url = url
        self.width = width
        self.height = height
        self.headless = headless
        # maxsize=2: always keep only the freshest frame or two, drop stale
        # ones rather than let a slow consumer fall behind real time
        self._frame_queue = queue.Queue(maxsize=2)
        self._stop = threading.Event()
        self._thread = None
        self._start_error = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def frames(self):
        """Generator yielding the latest available frame as a BGR numpy array."""
        while not self._stop.is_set():
            if self._start_error:
                raise self._start_error
            try:
                yield self._frame_queue.get(timeout=1.0)
            except queue.Empty:
                continue

    def _run(self):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                page = browser.new_page(viewport={"width": self.width, "height": self.height})
                page.goto(self.url, timeout=30000)
                cdp = page.context.new_cdp_session(page)
                cdp.on("Page.screencastFrame", self._on_frame(cdp))
                cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 80, "everyNthFrame": 1})

                while not self._stop.is_set():
                    page.wait_for_timeout(200)

                cdp.send("Page.stopScreencast")
                browser.close()
        except Exception as e:  # noqa: BLE001 - surface any startup/runtime error to frames()
            self._start_error = e

    def _on_frame(self, cdp):
        def handler(params):
            self._push_frame(params["data"])
            if self._stop.is_set():
                return  # browser/session may already be tearing down
            try:
                cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
            except Exception:
                pass  # session closed mid-ack during shutdown - harmless
        return handler

    def _push_frame(self, b64_data):
        jpg_bytes = base64.b64decode(b64_data)
        frame = cv2.imdecode(np.frombuffer(jpg_bytes, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return
        if self._frame_queue.full():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                pass
        self._frame_queue.put(frame)
