"""Per-frame ball/person detection for live play analysis, feeding
src/cv/trajectory.py via the shared src/cv/play_watcher.py video loop. Uses a
pretrained YOLOv8 model (COCO classes include "sports ball" and "person", so
this works out of the box with zero custom training data or fine-tuning) -
this is the zero-setup fallback; prefer src/cv/roboflow_tracker.py (a model
actually fine-tuned on American football) if you have a Roboflow API key,
see the README.

Be clear-eyed about what "out of the box" gets you: a small, fast-moving
football at typical broadcast resolution and motion blur is a genuinely hard
target for a generic COCO detector, which was trained on photos of
stationary/slow sports balls, not a spiral in flight. Expect missed
detections and false positives until this is fine-tuned on actual broadcast
football footage - which needs real labeled clips this environment doesn't
have. This module has not been run against real video for that reason (same
caveat as the scoreboard OCR reader, one level more true here). What's fully
real and tested is everything downstream of a detection - see trajectory.py.
"""

from src.cv.trajectory import Detection

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

_BALL_CLASS = "sports ball"
_PERSON_CLASS = "person"


class BallTracker:
    def __init__(self, model_name="yolov8n.pt", confidence=0.25):
        if YOLO is None:
            raise RuntimeError(
                "ultralytics is required for live play analysis. Install with: "
                "pip install ultralytics (downloads a small pretrained model on first run)."
            )
        self.model = YOLO(model_name)
        self.confidence = confidence

    def detect(self, frame, frame_idx) -> Detection:
        results = self.model(frame, verbose=False, conf=self.confidence)[0]
        ball_xy = None
        person_boxes = []

        for box in results.boxes:
            cls_name = results.names[int(box.cls[0])]
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            if cls_name == _BALL_CLASS and ball_xy is None:
                ball_xy = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
            elif cls_name == _PERSON_CLASS:
                person_boxes.append((x1, y1, x2 - x1, y2 - y1))

        return Detection(frame_idx=frame_idx, ball_xy=ball_xy, person_boxes=person_boxes)
