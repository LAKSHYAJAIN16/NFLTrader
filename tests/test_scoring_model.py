import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scoring_model import (
    Calibration, ScoreDistribution, ScoringModel, _team_score,
    home_win_prob, margin_bucket_prob, spread_cover_prob,
    team_total_over_prob, team_total_under_prob, total_over_prob, total_under_prob,
)


def even_dist(std_margin=13.5, total_mean=45.0, std_total=10.0):
    return ScoreDistribution(mean_margin=0.0, std_margin=std_margin,
                              mean_total=total_mean, std_total=std_total)


def favored_dist():
    return ScoreDistribution(mean_margin=7.0, std_margin=13.5, mean_total=45.0, std_total=10.0)


def test_even_matchup_is_a_coinflip():
    assert home_win_prob(even_dist()) == pytest.approx(0.5)


def test_favored_home_team_has_higher_win_prob():
    assert home_win_prob(favored_dist()) > 0.5


def test_home_and_away_cover_probs_sum_to_one_at_matching_lines():
    dist = favored_dist()
    home_covers = spread_cover_prob(dist, "home", -5.5)
    away_covers = spread_cover_prob(dist, "away", 5.5)
    assert home_covers + away_covers == pytest.approx(1.0, abs=1e-6)


def test_favorite_more_likely_to_cover_a_smaller_spread():
    dist = favored_dist()
    assert spread_cover_prob(dist, "home", -3.5) > spread_cover_prob(dist, "home", -10.5)


def test_total_over_under_sum_to_one():
    dist = even_dist()
    assert total_over_prob(dist, 44.5) + total_under_prob(dist, 44.5) == pytest.approx(1.0, abs=1e-6)


def test_total_over_less_likely_for_higher_line():
    dist = even_dist()
    assert total_over_prob(dist, 40.5) > total_over_prob(dist, 60.5)


def test_team_totals_sum_to_game_total_mean():
    dist = favored_dist()
    home_mean, _ = _team_score(dist, "home")
    away_mean, _ = _team_score(dist, "away")
    assert home_mean + away_mean == pytest.approx(dist.mean_total)


def test_team_total_over_under_sum_to_one():
    dist = favored_dist()
    assert (team_total_over_prob(dist, "home", 24.5) + team_total_under_prob(dist, "home", 24.5)) \
        == pytest.approx(1.0, abs=1e-6)


def test_favored_team_total_higher_than_underdog():
    dist = favored_dist()
    assert team_total_over_prob(dist, "home", 22.5) > team_total_over_prob(dist, "away", 22.5)


def test_margin_bucket_tie_is_narrow_and_small():
    dist = even_dist()
    tie_prob = margin_bucket_prob(dist, "home", 0, 0)
    blowout_prob = margin_bucket_prob(dist, "home", 1, 6)
    assert 0 < tie_prob < blowout_prob


def test_margin_bucket_open_ended_covers_the_tail():
    dist = favored_dist()
    big_win = margin_bucket_prob(dist, "home", 25, None)
    assert 0 < big_win < 0.5


def test_margin_buckets_plus_tie_approximate_full_win_probability():
    dist = favored_dist()
    win_buckets = [(1, 6), (7, 12), (13, 18), (19, 24), (25, None)]
    total = sum(margin_bucket_prob(dist, "home", lo, hi) for lo, hi in win_buckets)
    tie = margin_bucket_prob(dist, "home", 0, 0)
    # continuity correction shifts each bucket's edge by 0.5, so this only
    # lines up with the continuous win probability to within about one
    # density-slice's worth of probability mass, not exactly
    assert (total + tie) == pytest.approx(home_win_prob(dist), abs=0.02)


def test_period_distribution_scales_mean_and_variance_by_fraction():
    elo = _FakeElo({"KC": 1550, "SF": 1450})
    cal = Calibration(margin_slope=1 / 25.0, margin_intercept=0.0, margin_std=13.5,
                       total_mean=44.0, total_std=10.0)
    model = ScoringModel(elo, cal)

    full = model.period("KC", "SF", "full")
    half = model.period("KC", "SF", "1H")
    quarter = model.period("KC", "SF", "Q1")

    assert half.mean_margin == pytest.approx(full.mean_margin * 0.5)
    assert half.std_margin == pytest.approx(full.std_margin * (0.5 ** 0.5))
    assert quarter.mean_total == pytest.approx(full.mean_total * 0.25)


class _FakeElo:
    def __init__(self, ratings):
        self.ratings = ratings

    def get(self, team):
        return self.ratings.get(team, 1500.0)


# ---- live pricing ----

from src.elo import EloRatings
from src.scoring_model import LiveState


def _even_model():
    cal = Calibration(margin_slope=1 / 25.0, margin_intercept=0.0, margin_std=13.5,
                      total_mean=45.0, total_std=10.0)
    return ScoringModel(EloRatings({"KC": 1435.0, "SF": 1500.0}), cal)  # KC + home field = even


def test_live_before_kickoff_matches_pregame():
    model = _even_model()
    live = LiveState(0, 0, quarter=1, clock_seconds=900)
    assert model.price(("total_over", 44.5, "full"), "KC", "SF", live) == pytest.approx(
        model.price(("total_over", 44.5, "full"), "KC", "SF"))


def test_live_total_accounts_for_points_already_scored():
    model = _even_model()
    live = LiveState(28, 21, quarter=3, clock_seconds=900, quarter_scores=[(14, 7), (14, 14)])
    # 49 on the board at half: over 44.5 is all but settled
    assert model.price(("total_over", 44.5, "full"), "KC", "SF", live) > 0.99
    assert model.price(("total_over", 44.5, "full"), "KC", "SF") < 0.6


def test_finished_quarter_settles_from_linescores():
    model = _even_model()
    live = LiveState(14, 7, quarter=2, clock_seconds=600, quarter_scores=[(14, 7), (0, 0)])
    assert model.price(("win", "home", "Q1"), "KC", "SF", live) > 0.99
    assert model.price(("total_under", 20.5, "Q1"), "KC", "SF", live) < 0.01
    # Q3 hasn't started: still priced pregame
    assert model.price(("win", "home", "Q3"), "KC", "SF", live) == pytest.approx(
        model.price(("win", "home", "Q3"), "KC", "SF"))


def test_in_progress_quarter_blends_score_and_time_left():
    model = _even_model()
    early = LiveState(7, 0, quarter=2, clock_seconds=840, quarter_scores=[(0, 0), (7, 0)])
    late = LiveState(7, 0, quarter=2, clock_seconds=30, quarter_scores=[(0, 0), (7, 0)])
    p_early = model.price(("cover", "home", -3.5, "Q2"), "KC", "SF", early)
    p_late = model.price(("cover", "home", -3.5, "Q2"), "KC", "SF", late)
    assert 0.5 < p_early < p_late


def test_final_game_prices_resolve():
    model = _even_model()
    live = LiveState(24, 20, quarter=4, clock_seconds=0, final=True,
                     quarter_scores=[(7, 7), (3, 6), (7, 0), (7, 7)])
    assert model.price(("win", "home", "full"), "KC", "SF", live) > 0.99
    assert model.price(("cover", "away", 3.5, "full"), "KC", "SF", live) < 0.01
    assert model.price(("margin_bucket", "home", 1, 6), "KC", "SF", live) > 0.99
