import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cv.roboflow_tracker import RoboflowTracker


class FakeClient:
    def __init__(self, predictions_by_model):
        self.predictions_by_model = predictions_by_model
        self.calls = []

    def infer(self, frame, model_id):
        self.calls.append(model_id)
        return {"predictions": self.predictions_by_model.get(model_id, [])}


def test_requires_at_least_one_model_id():
    with pytest.raises(RuntimeError):
        RoboflowTracker(client=FakeClient({}))


def test_parses_ball_prediction_into_center_xy():
    fake = FakeClient({"ball-model/1": [
        {"class": "football", "x": 300.0, "y": 150.0, "width": 20.0, "height": 20.0, "confidence": 0.9},
    ]})
    tracker = RoboflowTracker(ball_model_id="ball-model/1", client=fake)
    detection = tracker.detect(frame="fake-frame", frame_idx=5)
    assert detection.ball_xy == (300.0, 150.0)
    assert detection.person_boxes == []


def test_parses_player_predictions_into_xywh_boxes():
    fake = FakeClient({"player-model/1": [
        {"class": "player", "x": 100.0, "y": 200.0, "width": 40.0, "height": 80.0, "confidence": 0.8},
    ]})
    tracker = RoboflowTracker(player_model_id="player-model/1", client=fake)
    detection = tracker.detect(frame="fake-frame", frame_idx=1)
    assert detection.ball_xy is None
    assert detection.person_boxes == [(80.0, 160.0, 40.0, 80.0)]


def test_ignores_predictions_outside_known_class_names():
    fake = FakeClient({"ball-model/1": [
        {"class": "referee", "x": 10.0, "y": 10.0, "width": 5.0, "height": 5.0, "confidence": 0.99},
    ]})
    tracker = RoboflowTracker(ball_model_id="ball-model/1", client=fake)
    detection = tracker.detect(frame="fake-frame", frame_idx=0)
    assert detection.ball_xy is None


def test_queries_both_models_when_both_configured():
    fake = FakeClient({"ball-model/1": [], "player-model/2": []})
    tracker = RoboflowTracker(ball_model_id="ball-model/1", player_model_id="player-model/2", client=fake)
    tracker.detect(frame="fake-frame", frame_idx=0)
    assert set(fake.calls) == {"ball-model/1", "player-model/2"}
