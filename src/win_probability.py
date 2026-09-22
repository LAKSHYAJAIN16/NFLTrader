"""Live home win probability from the pregame prior plus the in-game state.

Model: the final margin is what's already on the board plus a normal
distribution for the points still to come.

- The pregame prior fixes the expected full-game margin (the margin that
  makes P(home wins) equal the prior). The time left gets that share of it.
- The spread of what's to come shrinks with the square root of the time
  left, so a 7-point lead matters at kickoff and settles the game late.
- The team with the ball is credited the expected points of its field
  position (a standard NFL expected-points curve), damped when there's too
  little clock left to finish the drive.

This is the same shape `scoring_model` uses to price spreads/totals live, so
the win number and every market price come from one consistent model. It's
still a simplified approximation of nflfastR/ESPN-style models, not a
production one.
"""

import math
from statistics import NormalDist

import config

REGULATION_SECONDS = 60 * 60  # 4 quarters x 15 min
OT_SECONDS = 10 * 60          # regular-season overtime period

_STD_NORMAL = NormalDist()


def seconds_remaining(quarter, clock_seconds):
    """quarter: 1-4 (5=OT). clock_seconds: seconds left in that quarter."""
    if quarter >= 5:
        return clock_seconds
    quarters_left_after_this = max(0, 4 - quarter)
    return clock_seconds + quarters_left_after_this * 15 * 60


def seconds_elapsed(quarter, clock_seconds):
    """Game seconds played so far; overtime continues past 3600."""
    if quarter >= 5:
        return REGULATION_SECONDS + (OT_SECONDS - clock_seconds)
    return (quarter - 1) * 15 * 60 + (15 * 60 - clock_seconds)


def expected_points(yards_to_endzone):
    """Net expected points for the team with the ball (next score either way),
    roughly linear in field position: ~0.6 at their own 30, ~2.2 at midfield,
    ~6 at the goal line. Unknown field position counts as a typical drive
    start."""
    if yards_to_endzone is None:
        yards_to_endzone = 70
    return max(-0.6, 6.2 - 0.08 * yards_to_endzone)


def possession_value(possession_home, yards_to_endzone, secs_left):
    """Expected-points credit (home-signed) for whoever has the ball, damped
    when there's not enough clock to finish a drive."""
    if possession_home is None or secs_left <= 0:
        return 0.0
    ep = expected_points(yards_to_endzone) * min(1.0, secs_left / config.WP_DRIVE_SECONDS)
    return ep if possession_home else -ep


def implied_mean_margin(pregame_home_prob, margin_std=None):
    """The full-game expected home margin that makes P(home wins) equal the prior."""
    margin_std = margin_std or config.WP_MARGIN_STD
    p = min(max(pregame_home_prob, 1e-4), 1 - 1e-4)
    return margin_std * _STD_NORMAL.inv_cdf(p)


def live_home_win_prob(pregame_home_prob, home_score, away_score, quarter, clock_seconds,
                        possession_home=None, yard_line=None, margin_std=None):
    """Returns the model's live estimate that the home team wins.

    yard_line: yards to the possessing team's end zone (0-100), if known.
    """
    margin_std = margin_std or config.WP_MARGIN_STD
    secs_left = max(0.0, seconds_remaining(quarter, clock_seconds))
    score_diff = home_score - away_score

    if secs_left == 0:
        if score_diff != 0:
            return 0.999 if score_diff > 0 else 0.001
        # tied with no time left: overtime, a near coin flip leaning to the better team
        return min(max(_overtime_home_prob(pregame_home_prob), 0.001), 0.999)

    frac_left = min(secs_left, REGULATION_SECONDS) / REGULATION_SECONDS
    mean = (score_diff
            + implied_mean_margin(pregame_home_prob, margin_std) * frac_left
            + possession_value(possession_home, yard_line, secs_left))
    std = max(margin_std * math.sqrt(frac_left), 0.5)
    # margins are whole points: win outright past +0.5, and a final tie goes to overtime
    p_win = 1.0 - _STD_NORMAL.cdf((0.5 - mean) / std)
    p_tie = _STD_NORMAL.cdf((0.5 - mean) / std) - _STD_NORMAL.cdf((-0.5 - mean) / std)
    p = p_win + p_tie * _overtime_home_prob(pregame_home_prob)
    return min(max(p, 0.001), 0.999)


def _overtime_home_prob(pregame_home_prob):
    return 0.5 + (pregame_home_prob - 0.5) * 0.5
