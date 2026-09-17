"""Predicts whether a thrown ball is likely to be caught WHILE it's still in
the air - not after the play result posts to a score feed. This is what
actually earns latency: a score/clock feed (src/espn_feed.py) can only ever
tell you a play already happened, seconds after the fact. This module fits
a trajectory to the ball's last few tracked positions, projects where it's
going to land, and estimates catch probability from how many people are
contesting that spot - updating every frame the ball is airborne.

Pure math, no video/model dependency, so it's fully testable without a real
broadcast (see tests/test_trajectory.py and tools/demo_play_analysis.py).
The piece that can't be tested here is the actual frame-to-frame detector
that produces these (x, y) ball/person positions in the first place -
see src/cv/ball_tracker.py for that, and its own honesty note.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import config

Point = Tuple[float, float]
Box = Tuple[float, float, float, float]  # x, y, w, h


@dataclass
class Detection:
    """One frame's worth of raw detections, in pixel coordinates."""
    frame_idx: int
    ball_xy: Optional[Point]
    person_boxes: List[Box] = field(default_factory=list)


@dataclass
class PlayPrediction:
    frame_idx: int
    in_flight: bool
    catch_probability: Optional[float]
    predicted_landing: Optional[Point]
    contested_by: int
    message: str


class TrajectoryTracker:
    def __init__(self, min_points=4, lookahead_frames=4,
                 velocity_threshold=config.BALL_AIRBORNE_VELOCITY_PX):
        self.min_points = min_points
        self.lookahead_frames = lookahead_frames
        self.velocity_threshold = velocity_threshold
        self.buffer: List[Detection] = []
        self.in_flight = False

    def reset(self):
        self.buffer = []
        self.in_flight = False

    def update(self, detection: Detection) -> Optional[PlayPrediction]:
        if detection.ball_xy is None:
            result = None
            if self.in_flight and len(self.buffer) >= self.min_points:
                result = PlayPrediction(
                    frame_idx=detection.frame_idx, in_flight=False, catch_probability=None,
                    predicted_landing=None, contested_by=0,
                    message="Ball no longer tracked - play resolved "
                            "(catch, incompletion, or pass defensed).",
                )
            self.reset()
            return result

        self.buffer.append(detection)
        if len(self.buffer) > 30:
            self.buffer.pop(0)

        if not self.in_flight:
            if len(self.buffer) < self.min_points or not self._is_airborne():
                return None
            self.in_flight = True

        landing = self._project_landing()
        if landing is None:
            return None

        contested_by, min_dist = self._contest(landing, detection.person_boxes)
        catch_prob = self._catch_probability(min_dist, contested_by)

        return PlayPrediction(
            frame_idx=detection.frame_idx, in_flight=True,
            catch_probability=catch_prob, predicted_landing=landing, contested_by=contested_by,
            message=f"Ball in the air -> catch probability ~{catch_prob:.0%} "
                    f"({contested_by} player(s) contesting the projected landing spot)",
        )

    def _is_airborne(self):
        recent = self.buffer[-self.min_points:]
        vy = recent[-1].ball_xy[1] - recent[0].ball_xy[1]
        return abs(vy) >= self.velocity_threshold

    def _project_landing(self) -> Optional[Point]:
        pts = self.buffer[-self.min_points:]
        n = len(pts)
        ts = list(range(n))
        xs = [p.ball_xy[0] for p in pts]
        ys = [p.ball_xy[1] for p in pts]

        try:
            a, b, c = _fit_quadratic(ts, ys)
        except ZeroDivisionError:
            return None

        vx = (xs[-1] - xs[0]) / max(1, n - 1)
        t_future = (n - 1) + self.lookahead_frames
        x_future = xs[-1] + vx * self.lookahead_frames
        y_future = a * t_future ** 2 + b * t_future + c
        return (x_future, y_future)

    @staticmethod
    def _contest(landing, person_boxes):
        if not person_boxes:
            return 0, None
        dists = []
        for (x, y, w, h) in person_boxes:
            cx, cy = x + w / 2.0, y + h / 2.0
            dists.append(((cx - landing[0]) ** 2 + (cy - landing[1]) ** 2) ** 0.5)
        dists.sort()
        nearby = sum(1 for d in dists if d <= config.CATCH_CONTEST_RADIUS_PX)
        return nearby, dists[0]

    @staticmethod
    def _catch_probability(min_dist, contested_by):
        if min_dist is None:
            return config.CATCH_PROB_UNCONTESTED
        proximity_factor = min(1.0, min_dist / config.CATCH_CONTEST_RADIUS_PX)
        base = config.CATCH_PROB_UNCONTESTED - (1 - proximity_factor) * config.CATCH_PROB_SWING
        penalty = 0.05 * max(0, contested_by - 1)  # extra bodies compound the contest further
        return max(0.05, min(0.97, base - penalty))


def _fit_quadratic(ts, ys):
    """Closed-form least-squares fit of y = a*t^2 + b*t + c, no numpy needed."""
    n = len(ts)
    sx = sum(ts)
    sx2 = sum(t * t for t in ts)
    sx3 = sum(t ** 3 for t in ts)
    sx4 = sum(t ** 4 for t in ts)
    sy = sum(ys)
    sxy = sum(t * y for t, y in zip(ts, ys))
    sx2y = sum((t ** 2) * y for t, y in zip(ts, ys))

    a_matrix = [[sx4, sx3, sx2], [sx3, sx2, sx], [sx2, sx, n]]
    b_vector = [sx2y, sxy, sy]
    det = _det3(a_matrix)
    if det == 0:
        raise ZeroDivisionError("degenerate trajectory fit")

    a = _det3(_replace_col(a_matrix, 0, b_vector)) / det
    b = _det3(_replace_col(a_matrix, 1, b_vector)) / det
    c = _det3(_replace_col(a_matrix, 2, b_vector)) / det
    return a, b, c


def _det3(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def _replace_col(m, col, vals):
    return [[vals[i] if c == col else m[i][c] for c in range(3)] for i in range(3)]
