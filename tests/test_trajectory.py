import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cv.trajectory import Detection, TrajectoryTracker


def parabolic_arc(n_frames, x0=100, vx=15, y0=400, vy0=-40, gravity=3.0):
    """Simulates a ball thrown from (x0, y0) moving right and arcing down,
    like a football's pixel trajectory across broadcast frames."""
    points = []
    for t in range(n_frames):
        x = x0 + vx * t
        y = y0 + vy0 * t + gravity * t * t
        points.append((x, y))
    return points


def test_no_detection_yields_no_prediction_when_not_in_flight():
    tracker = TrajectoryTracker()
    result = tracker.update(Detection(frame_idx=0, ball_xy=None))
    assert result is None


def test_stationary_ball_is_not_airborne():
    tracker = TrajectoryTracker(min_points=4)
    for i in range(5):
        result = tracker.update(Detection(frame_idx=i, ball_xy=(100.0, 400.0)))
    assert tracker.in_flight is False
    assert result is None


def test_thrown_ball_is_detected_as_in_flight_and_predicts_landing():
    tracker = TrajectoryTracker(min_points=4, lookahead_frames=4)
    arc = parabolic_arc(10)
    result = None
    for i, xy in enumerate(arc):
        result = tracker.update(Detection(frame_idx=i, ball_xy=xy))
    assert tracker.in_flight is True
    assert result is not None
    assert result.in_flight is True
    assert result.predicted_landing is not None
    assert 0.0 <= result.catch_probability <= 1.0


def test_uncontested_catch_has_high_probability():
    tracker = TrajectoryTracker(min_points=4, lookahead_frames=2)
    arc = parabolic_arc(8)
    result = None
    for i, xy in enumerate(arc):
        # no person boxes at all -> nothing contesting the catch
        result = tracker.update(Detection(frame_idx=i, ball_xy=xy, person_boxes=[]))
    assert result.catch_probability == pytest.approx(0.85)


def test_defender_right_on_the_landing_spot_lowers_catch_probability():
    tracker_open = TrajectoryTracker(min_points=4, lookahead_frames=2)
    tracker_covered = TrajectoryTracker(min_points=4, lookahead_frames=2)
    arc = parabolic_arc(8)

    open_result = None
    covered_result = None
    for i, xy in enumerate(arc):
        open_result = tracker_open.update(Detection(frame_idx=i, ball_xy=xy, person_boxes=[]))
        landing_guess = (xy[0] + 30, xy[1] + 30)  # a body camped near where the ball is heading
        covered_result = tracker_covered.update(
            Detection(frame_idx=i, ball_xy=xy, person_boxes=[(landing_guess[0] - 10, landing_guess[1] - 10, 20, 20)])
        )

    assert covered_result.catch_probability < open_result.catch_probability


def test_ball_disappearing_mid_flight_resolves_the_play():
    tracker = TrajectoryTracker(min_points=4, lookahead_frames=2)
    arc = parabolic_arc(8)
    for i, xy in enumerate(arc):
        tracker.update(Detection(frame_idx=i, ball_xy=xy))
    assert tracker.in_flight is True

    result = tracker.update(Detection(frame_idx=99, ball_xy=None))
    assert result is not None
    assert result.in_flight is False
    assert tracker.in_flight is False  # tracker resets once the play resolves
