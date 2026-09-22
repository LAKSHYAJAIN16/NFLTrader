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


def test_decided_when_no_time_left_and_not_tied():
    # a 10-pt final with an underdog prior must still resolve to the winner
    assert live_home_win_prob(0.3, 41, 31, quarter=4, clock_seconds=0) > 0.99
    assert live_home_win_prob(0.7, 31, 41, quarter=4, clock_seconds=0) < 0.01


def test_tied_at_end_of_regulation_is_not_decided():
    p = live_home_win_prob(0.6, 20, 20, quarter=4, clock_seconds=0)
    assert 0.01 < p < 0.99


def test_an_early_lead_counts_from_kickoff():
    # a 7-0 lead in the 1st quarter is worth a lot more than a coin flip
    even = live_home_win_prob(0.5, 0, 0, 1, 12 * 60)
    up_seven = live_home_win_prob(0.5, 7, 0, 1, 12 * 60)
    assert up_seven - even > 0.15


def test_a_touchdown_from_the_one_is_mostly_priced_in():
    # BUF 1st & goal at the DET 1, then scores and kicks off: the drive already
    # earned most of the value, so the TD itself must not swing it backwards
    at_the_one = live_home_win_prob(0.6, 0, 0, 1, 9 * 60 + 15, possession_home=True, yard_line=1)
    after_td = live_home_win_prob(0.6, 7, 0, 1, 9 * 60 + 9, possession_home=False, yard_line=70)
    assert after_td >= at_the_one - 0.01


def test_possession_matters_less_with_no_time_to_drive():
    lots = live_home_win_prob(0.5, 14, 14, 4, 600, possession_home=True, yard_line=50)
    none = live_home_win_prob(0.5, 14, 14, 4, 5, possession_home=True, yard_line=50)
    base = live_home_win_prob(0.5, 14, 14, 4, 5)
    assert lots > 0.5
    assert abs(none - base) < (lots - base) / 3
