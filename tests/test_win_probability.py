import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.win_probability import live_home_win_prob, seconds_remaining


def test_seconds_remaining_start_of_game():
    assert seconds_remaining(1, 15 * 60) == 60 * 60


def test_seconds_remaining_end_of_game():
    assert seconds_remaining(4, 0) == 0


def test_pregame_prior_dominates_at_kickoff():
    wp = live_home_win_prob(pregame_home_prob=0.7, home_score=0, away_score=0,
                             quarter=1, clock_seconds=15 * 60)
    assert abs(wp - 0.7) < 0.05


def test_score_dominates_late_and_close():
    wp_leading = live_home_win_prob(pregame_home_prob=0.3, home_score=21, away_score=3,
                                     quarter=4, clock_seconds=30)
    assert wp_leading > 0.7  # big lead late overrides a weak pregame prior


def test_possession_nudges_win_prob():
    wp_with_ball = live_home_win_prob(0.5, 14, 14, 4, 300, possession_home=True)
    wp_without_ball = live_home_win_prob(0.5, 14, 14, 4, 300, possession_home=False)
    assert wp_with_ball > wp_without_ball
