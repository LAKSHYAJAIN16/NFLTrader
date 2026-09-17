"""Runs the real TrajectoryTracker over a scripted throw - no video/YOLO
required - so you can see catch-probability prediction working frame by
frame while the ball is "in the air", before the play resolves.

Two throws are simulated: one uncontested (nobody near the catch point) and
one where a defender closes in and undercuts the catch probability as the
ball arrives - the same math src/cv/ball_tracker.py would feed from real
detections, just with hand-scripted (x, y) points standing in for what a
real detector would output frame by frame.

Usage: python tools/demo_play_analysis.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cv.trajectory import Detection, TrajectoryTracker


def simulate_throw(defender_closing=False, n_frames=12):
    """A ball thrown from (120, 380) arcing out to roughly (600, 300)."""
    tracker = TrajectoryTracker(min_points=4, lookahead_frames=4)
    x0, y0 = 120.0, 380.0
    vx, vy0, gravity = 42.0, -55.0, 4.2

    ball_positions = [(x0 + vx * t, y0 + vy0 * t + gravity * t * t) for t in range(n_frames)]
    landing_point = ball_positions[-1]  # where the throw actually ends up

    for t, (x, y) in enumerate(ball_positions):
        person_boxes = []
        if defender_closing and t >= 5:
            # a defender sitting in the zone the throw is heading toward
            person_boxes = [(landing_point[0] - 15, landing_point[1] - 15, 30, 30)]

        prediction = tracker.update(Detection(frame_idx=t, ball_xy=(x, y), person_boxes=person_boxes))
        if prediction and prediction.in_flight:
            print(f"  frame {t:2d}: {prediction.message}")

    final = tracker.update(Detection(frame_idx=n_frames, ball_xy=None))
    if final:
        print(f"  frame {n_frames:2d}: {final.message}")


def main():
    print("Uncontested throw (nobody near the landing spot):")
    simulate_throw(defender_closing=False)

    print("\nContested throw (a defender closes in on the landing spot):")
    simulate_throw(defender_closing=True)


if __name__ == "__main__":
    main()
