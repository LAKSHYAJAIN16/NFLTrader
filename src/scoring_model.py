"""A calibrated (margin, total) score distribution derived from Elo, used to
price every market family Polymarket lists for a game - moneyline, spreads,
totals, team totals, and exact-margin buckets, across the full game and every
half/quarter breakdown - not just the full-game moneyline.

The Elo model only ever gave us P(home wins). Spreads need a margin-of-victory
distribution, totals need a points distribution, team totals need both split
per team. Rather than inventing constants, `calibrate()` replays the same
nflverse historical results used to bootstrap Elo and fits: margin ~ a *
pregame_elo_diff + b (least squares), plus the league-wide std of margin and
the mean/std of game totals - all real numbers pulled from history, not
guessed.

Sub-period (half/quarter) distributions are a deliberately simple
approximation: mean scales with the period's share of the game, variance
scales linearly with it (so std scales with sqrt(fraction)) - the standard
simplifying assumption for a Poisson-ish scoring process spread over time.
This is not what nflfastR-grade production models do, but it is internally
consistent (a half's distribution is literally the sum of two quarters'
worth of the full-game distribution) and calibrated against real data, not
invented.
"""

import math
from dataclasses import dataclass

import config

PERIOD_FRACTIONS = {"full": 1.0, "1H": 0.5, "2H": 0.5, "Q1": 0.25, "Q2": 0.25, "Q3": 0.25, "Q4": 0.25}


@dataclass
class Calibration:
    margin_slope: float
    margin_intercept: float
    margin_std: float
    total_mean: float
    total_std: float


@dataclass
class ScoreDistribution:
    mean_margin: float   # home - away, full period
    std_margin: float
    mean_total: float     # home + away, full period
    std_total: float


def calibrate(min_season=None, max_season=None):
    """Replays historical games chronologically, returning a freshly-bootstrapped
    EloRatings (same as data_loader.bootstrap_elo would produce) alongside a
    Calibration fit from the same pass - one source of truth for both.
    """
    from src import data_loader
    from src.elo import EloRatings

    games = data_loader.load_completed_games(min_season=min_season, max_season=max_season)
    elo = EloRatings()

    elo_diffs, margins, totals = [], [], []
    for g in games:
        elo_diff = (elo.get(g["home_team"]) + config.ELO_HOME_ADVANTAGE) - elo.get(g["away_team"])
        elo_diffs.append(elo_diff)
        margins.append(g["home_score"] - g["away_score"])
        totals.append(g["home_score"] + g["away_score"])
        elo.update(g["home_team"], g["away_team"], g["home_score"], g["away_score"])

    if len(games) < 10:
        # not enough history to calibrate a regression - fall back to
        # reasonable NFL-wide constants (538's ~25 Elo points per point of
        # spread, ~21-point historical scoring std, ~45-point total)
        return elo, Calibration(margin_slope=1 / 25.0, margin_intercept=0.0,
                                 margin_std=13.5, total_mean=45.0, total_std=10.0)

    slope, intercept = _fit_line(elo_diffs, margins)
    residuals = [m - (slope * d + intercept) for d, m in zip(elo_diffs, margins)]
    margin_std = _std(residuals)
    total_mean = _mean(totals)
    total_std = _std(totals)

    return elo, Calibration(slope, intercept, margin_std, total_mean, total_std)


class ScoringModel:
    def __init__(self, elo, calibration):
        self.elo = elo
        self.cal = calibration

    def full_game(self, home_abbr, away_abbr) -> ScoreDistribution:
        elo_diff = (self.elo.get(home_abbr) + config.ELO_HOME_ADVANTAGE) - self.elo.get(away_abbr)
        mean_margin = self.cal.margin_slope * elo_diff + self.cal.margin_intercept
        return ScoreDistribution(mean_margin, self.cal.margin_std, self.cal.total_mean, self.cal.total_std)

    def period(self, home_abbr, away_abbr, period="full") -> ScoreDistribution:
        fraction = PERIOD_FRACTIONS[period]
        full = self.full_game(home_abbr, away_abbr)
        return ScoreDistribution(
            mean_margin=full.mean_margin * fraction,
            std_margin=full.std_margin * math.sqrt(fraction),
            mean_total=full.mean_total * fraction,
            std_total=full.std_total * math.sqrt(fraction),
        )

    def price(self, spec, home_abbr, away_abbr) -> float:
        """Prices any (kind, ...) spec produced by src/market_catalog.py."""
        kind = spec[0]

        if kind == "win":
            _, side, period = spec
            dist = self.period(home_abbr, away_abbr, period)
            p = home_win_prob(dist)
            return p if side == "home" else 1.0 - p

        if kind == "cover":
            _, side, line, period = spec
            dist = self.period(home_abbr, away_abbr, period)
            return spread_cover_prob(dist, side, line)

        if kind in ("total_over", "total_under"):
            _, line, period = spec
            dist = self.period(home_abbr, away_abbr, period)
            return total_over_prob(dist, line) if kind == "total_over" else total_under_prob(dist, line)

        if kind in ("team_total_over", "team_total_under"):
            _, side, line, period = spec
            dist = self.period(home_abbr, away_abbr, period)
            return (team_total_over_prob(dist, side, line) if kind == "team_total_over"
                    else team_total_under_prob(dist, side, line))

        if kind in ("margin_bucket", "margin_bucket_no"):
            _, side, low, high = spec
            dist = self.full_game(home_abbr, away_abbr)
            p = margin_bucket_prob(dist, side, low, high)
            return p if kind == "margin_bucket" else 1.0 - p

        raise ValueError(f"unknown pricing spec kind: {kind!r}")


def resolve_outcome(spec, home_score, away_score):
    """Given a market_catalog spec and a game's FINAL score, returns True/False
    for whether that outcome actually happened, or None if it can't be
    determined from a final score alone (any half/quarter-period spec - that
    needs real quarter-by-quarter scoring data this project doesn't have a
    source for yet, so those positions are left open rather than guessed at).
    """
    kind = spec[0]
    margin = home_score - away_score
    total = home_score + away_score

    period = spec[-1] if kind in ("win", "cover", "total_over", "total_under",
                                   "team_total_over", "team_total_under") else "full"
    if period != "full":
        return None

    if kind == "win":
        _, side, _period = spec
        team_margin = margin if side == "home" else -margin
        return team_margin > 0

    if kind == "cover":
        _, side, line, _period = spec
        team_margin = margin if side == "home" else -margin
        return team_margin > -line

    if kind in ("total_over", "total_under"):
        _, line, _period = spec
        return (total > line) if kind == "total_over" else (total < line)

    if kind in ("team_total_over", "team_total_under"):
        _, side, line, _period = spec
        team_score = home_score if side == "home" else away_score
        return (team_score > line) if kind == "team_total_over" else (team_score < line)

    if kind in ("margin_bucket", "margin_bucket_no"):
        _, side, low, high = spec
        team_margin = margin if side == "home" else -margin
        in_range = (low is None or team_margin >= low) and (high is None or team_margin <= high)
        hit = in_range and (team_margin > 0 or (low, high) == (0, 0))
        return hit if kind == "margin_bucket" else not hit

    return None


def _team_margin(dist: ScoreDistribution, side: str):
    """(mean, std) of that side's own signed margin (positive = winning)."""
    mean = dist.mean_margin if side == "home" else -dist.mean_margin
    return mean, dist.std_margin


def home_win_prob(dist: ScoreDistribution) -> float:
    return 1.0 - _norm_cdf(0.0, dist.mean_margin, dist.std_margin)


def spread_cover_prob(dist: ScoreDistribution, side: str, line: float) -> float:
    """`line` is the number as displayed for that side (e.g. home line -5.5
    means home must win by more than 5.5; away line +5.5 means away covers
    unless they lose by more than 5.5)."""
    mean, std = _team_margin(dist, side)
    return 1.0 - _norm_cdf(-line, mean, std)


def total_over_prob(dist: ScoreDistribution, line: float) -> float:
    return 1.0 - _norm_cdf(line, dist.mean_total, dist.std_total)


def total_under_prob(dist: ScoreDistribution, line: float) -> float:
    return _norm_cdf(line, dist.mean_total, dist.std_total)


def team_total_over_prob(dist: ScoreDistribution, side: str, line: float) -> float:
    mean, std = _team_score(dist, side)
    return 1.0 - _norm_cdf(line, mean, std)


def team_total_under_prob(dist: ScoreDistribution, side: str, line: float) -> float:
    mean, std = _team_score(dist, side)
    return _norm_cdf(line, mean, std)


def margin_bucket_prob(dist: ScoreDistribution, side: str, low, high) -> float:
    """Probability that `side`'s margin of victory falls in [low, high]
    (either bound may be None for an open-ended "N+" bucket), with a +/-0.5
    continuity correction since NFL margins are always integers."""
    mean, std = _team_margin(dist, side)
    lo = -0.5 if low is None else low - 0.5
    hi = math.inf if high is None else high + 0.5
    return _norm_cdf(hi, mean, std) - _norm_cdf(lo, mean, std)


def _team_score(dist: ScoreDistribution, side: str):
    """(mean, std) of that side's own points scored, assuming margin and
    total are independent (a simplifying approximation - in reality they're
    mildly correlated via game script, but this keeps the model tractable)."""
    sign = 1 if side == "home" else -1
    mean = (dist.mean_total + sign * dist.mean_margin) / 2.0
    std = math.sqrt(dist.std_total ** 2 + dist.std_margin ** 2) / 2.0
    return mean, std


def _norm_cdf(x, mean, std):
    if std <= 0:
        return 1.0 if x < mean else 0.0
    return 0.5 * (1.0 + math.erf((x - mean) / (std * math.sqrt(2.0))))


def _mean(values):
    return sum(values) / len(values)


def _std(values):
    m = _mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def _fit_line(xs, ys):
    """Closed-form least-squares slope/intercept for y = slope*x + intercept."""
    n = len(xs)
    mean_x, mean_y = _mean(xs), _mean(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x == 0:
        return 0.0, mean_y
    slope = cov / var_x
    intercept = mean_y - slope * mean_x
    return slope, intercept
