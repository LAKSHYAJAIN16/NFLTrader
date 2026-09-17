"""Blends the pregame Elo prior with a live in-game state (from CV) into a
live home win probability. This is a simplified approximation of the kind of
model nflfastR/ESPN use, not a calibrated production model - good enough to
show whether the market has over/under-reacted to what's happening on the field.
"""

import math

import config

REGULATION_SECONDS = 60 * 60  # 4 quarters x 15 min


def _logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def seconds_remaining(quarter, clock_seconds):
    """quarter: 1-4 (5=OT). clock_seconds: seconds left in that quarter."""
    if quarter >= 5:
        return clock_seconds
    quarters_left_after_this = max(0, 4 - quarter)
    return clock_seconds + quarters_left_after_this * 15 * 60


def live_home_win_prob(pregame_home_prob, home_score, away_score, quarter, clock_seconds,
                        possession_home=None, yard_line=None):
    """Returns the model's live estimate that the home team wins.

    - Early in the game the pregame Elo prior dominates.
    - As time runs out, the actual score differential dominates.
    - Possession of the ball is worth a small bump.
    - Field position (yard_line: yards to the possessing team's end zone, 0-100)
      adds a further bump proportional to how close they are to scoring.
    """
    secs_left = max(0.0, min(seconds_remaining(quarter, clock_seconds), REGULATION_SECONDS))
    time_frac_elapsed = 1.0 - (secs_left / REGULATION_SECONDS)
    score_weight = config.WP_SCORE_WEIGHT_MAX * time_frac_elapsed

    score_diff = home_score - away_score
    # normalize: a two-score (~16 pt) lead is treated as ~ decisive once weighted in
    score_component = _sigmoid(score_diff / 8.0)

    prior_component = pregame_home_prob
    blended = (1 - score_weight) * prior_component + score_weight * score_component

    if possession_home is True:
        blended += config.WP_POSSESSION_BONUS * (1 - time_frac_elapsed * 0.5)
    elif possession_home is False:
        blended -= config.WP_POSSESSION_BONUS * (1 - time_frac_elapsed * 0.5)

    if yard_line is not None and possession_home is not None:
        field_position_bonus = config.WP_FIELD_POSITION_MAX * (1 - yard_line / 100.0)
        blended += field_position_bonus if possession_home else -field_position_bonus

    return min(max(blended, 0.001), 0.999)
