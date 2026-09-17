import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scoring_model import resolve_outcome

# BUF (home) 27, DET (away) 20 -> home margin +7, total 47
HOME, AWAY = 27, 20


def test_moneyline_win_resolves():
    assert resolve_outcome(("win", "home", "full"), HOME, AWAY) is True
    assert resolve_outcome(("win", "away", "full"), HOME, AWAY) is False


def test_moneyline_subperiod_is_unresolvable():
    assert resolve_outcome(("win", "home", "1H"), HOME, AWAY) is None
    assert resolve_outcome(("win", "home", "Q3"), HOME, AWAY) is None


def test_spread_cover_resolves():
    # home favored by -3.5: won by 7, so they cover
    assert resolve_outcome(("cover", "home", -3.5, "full"), HOME, AWAY) is True
    # home favored by -10.5: won by only 7, so they don't cover
    assert resolve_outcome(("cover", "home", -10.5, "full"), HOME, AWAY) is False
    # away getting +10.5: they lost by 7, well within it, so they cover
    assert resolve_outcome(("cover", "away", 10.5, "full"), HOME, AWAY) is True


def test_total_over_under_resolves():
    assert resolve_outcome(("total_over", 44.5, "full"), HOME, AWAY) is True
    assert resolve_outcome(("total_under", 44.5, "full"), HOME, AWAY) is False
    assert resolve_outcome(("total_over", 50.5, "full"), HOME, AWAY) is False


def test_team_total_resolves():
    assert resolve_outcome(("team_total_over", "home", 24.5, "full"), HOME, AWAY) is True
    assert resolve_outcome(("team_total_under", "away", 24.5, "full"), HOME, AWAY) is True


def test_margin_bucket_resolves():
    assert resolve_outcome(("margin_bucket", "home", 1, 6), HOME, AWAY) is False  # won by 7, not 1-6
    assert resolve_outcome(("margin_bucket", "home", 7, 12), HOME, AWAY) is True
    assert resolve_outcome(("margin_bucket_no", "home", 7, 12), HOME, AWAY) is False
    assert resolve_outcome(("margin_bucket", "away", 7, 12), HOME, AWAY) is False  # away lost, not won


def test_margin_bucket_open_ended_resolves():
    assert resolve_outcome(("margin_bucket", "home", 25, None), HOME, AWAY) is False
    assert resolve_outcome(("margin_bucket", "home", 1, None), HOME, AWAY) is True


def test_margin_bucket_tie_resolves_false_on_a_decisive_game():
    assert resolve_outcome(("margin_bucket", "home", 0, 0), HOME, AWAY) is False


def test_margin_bucket_tie_resolves_true_on_an_actual_tie():
    assert resolve_outcome(("margin_bucket", "home", 0, 0), 20, 20) is True
