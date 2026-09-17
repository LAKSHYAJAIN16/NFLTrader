"""Ball/player detection via a Roboflow-hosted model - a swap-in alternative
to src/cv/ball_tracker.py's generic COCO YOLO detector, driven by the same
src/cv/play_watcher.py loop (same `.detect(frame, frame_idx)` interface).

Why this over COCO YOLO: COCO's "sports ball" class was trained on photos of
mostly-stationary balls across many sports, not a small fast-moving NFL
football in broadcast motion blur - recall is poor. Roboflow Universe hosts
models fine-tuned specifically on American football footage (Roboflow's own
blog post demonstrates RF-DETR + ByteTrack fine-tuned on an NFL player
dataset at 74.8% mAP@50 - https://blog.roboflow.com/american-football-player-tracker/)
and separately lists ball-specific and player-specific American football
detection models under https://universe.roboflow.com/search?q=class%3Afootball -
several similarly-named Universe projects are soccer, not NFL, so pick
carefully and sanity-check a model's sample predictions before trusting it.

Needs a free Roboflow account + API key (ROBOFLOW_API_KEY env var) and at
least one model id to call (ROBOFLOW_BALL_MODEL_ID / ROBOFLOW_PLAYER_MODEL_ID,
each "project-slug/version" - copy this straight from the model's Universe
page). Like ball_tracker.py and the CV scoreboard reader, this hasn't been
run against a live feed in this environment - verify class names and
detection quality against your own footage before trusting it.
"""

import os

from src.cv.trajectory import Detection

try:
    from inference_sdk import InferenceHTTPClient
except ImportError:
    InferenceHTTPClient = None

SERVERLESS_API_URL = "https://serverless.roboflow.com"

# Class-name aliases across different Universe models - extend as needed
# once you know what your chosen model actually calls its classes.
_BALL_CLASS_NAMES = {"ball", "football", "sports ball", "nfl ball"}
_PERSON_CLASS_NAMES = {"player", "person", "quarterback", "qb"}


def is_configured():
    return bool(os.environ.get("ROBOFLOW_API_KEY")) and InferenceHTTPClient is not None


class RoboflowTracker:
    def __init__(self, ball_model_id=None, player_model_id=None, client=None):
        self.ball_model_id = ball_model_id or os.environ.get("ROBOFLOW_BALL_MODEL_ID")
        self.player_model_id = player_model_id or os.environ.get("ROBOFLOW_PLAYER_MODEL_ID")
        if not self.ball_model_id and not self.player_model_id:
            raise RuntimeError(
                "Set ROBOFLOW_BALL_MODEL_ID and/or ROBOFLOW_PLAYER_MODEL_ID to a Universe "
                "model's 'project-slug/version' (see this module's docstring)."
            )

        if client is not None:
            self.client = client  # for tests: inject a fake with a .infer() method
            return

        if InferenceHTTPClient is None:
            raise RuntimeError(
                "inference-sdk is required for Roboflow detection. Install with: "
                "pip install inference-sdk"
            )
        api_key = os.environ.get("ROBOFLOW_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Set ROBOFLOW_API_KEY (free at roboflow.com) to use Roboflow detection."
            )
        self.client = InferenceHTTPClient(api_url=SERVERLESS_API_URL, api_key=api_key)

    def detect(self, frame, frame_idx) -> Detection:
        ball_xy = None
        person_boxes = []

        if self.ball_model_id:
            for pred in self._predict(frame, self.ball_model_id):
                if pred["class"].lower() in _BALL_CLASS_NAMES:
                    ball_xy = (pred["x"], pred["y"])
                    break

        if self.player_model_id:
            for pred in self._predict(frame, self.player_model_id):
                if pred["class"].lower() in _PERSON_CLASS_NAMES:
                    w, h = pred["width"], pred["height"]
                    person_boxes.append((pred["x"] - w / 2.0, pred["y"] - h / 2.0, w, h))

        return Detection(frame_idx=frame_idx, ball_xy=ball_xy, person_boxes=person_boxes)

    def _predict(self, frame, model_id):
        result = self.client.infer(frame, model_id=model_id)
        return result.get("predictions", [])
