"""Turns a stream of CV-read GameStates into plain-English win-probability
insights: for each meaningful change on the field, explain whether the win
probability should move up or down, for which team, and why.
"""

from dataclasses import dataclass
from typing import Optional

import config
from src import win_probability
from src.cv.game_state import GameState

_SCORE_LABELS = {2: "safety", 3: "field_goal", 6: "touchdown", 7: "touchdown", 8: "touchdown"}


@dataclass
class Insight:
    win_prob_before: float
    win_prob_after: float
    event_type: str
    message: str
    home_score: int
    away_score: int
    timestamp: Optional[float] = None

    @property
    def delta(self):
        return self.win_prob_after - self.win_prob_before

    @property
    def direction(self):
        if self.delta > 1e-9:
            return "up"
        if self.delta < -1e-9:
            return "down"
        return "flat"


class InsightEngine:
    """Feed it successive GameState reads (e.g. from ScoreboardReader.read_video);
    it maintains the running win probability and emits an Insight whenever
    something happened that should move it.
    """

    def __init__(self, pregame_home_prob, home_abbr="HOME", away_abbr="AWAY"):
        self.pregame_home_prob = pregame_home_prob
        self.home_abbr = home_abbr
        self.away_abbr = away_abbr
        self.prev_state: Optional[GameState] = None
        self.win_prob = pregame_home_prob

    def process(self, state: GameState) -> Optional[Insight]:
        prev = self.prev_state
        wp_before = self.win_prob
        wp_after = win_probability.live_home_win_prob(
            self.pregame_home_prob, state.home_score, state.away_score,
            state.quarter, state.clock_seconds, state.possession_home, state.yard_line,
        )
        event_type = self._classify(prev, state)

        self.prev_state = state
        self.win_prob = wp_after

        delta = wp_after - wp_before
        if event_type == "drift" and abs(delta) < config.INSIGHT_MIN_DELTA:
            return None

        return Insight(
            win_prob_before=wp_before,
            win_prob_after=wp_after,
            event_type=event_type,
            message=self._format_message(wp_before, wp_after, event_type, state),
            home_score=state.home_score,
            away_score=state.away_score,
            timestamp=state.timestamp,
        )

    def _classify(self, prev, curr):
        if prev is None:
            is_game_start = curr.quarter == 1 and curr.clock_seconds >= 14 * 60
            return "kickoff" if is_game_start else "tracking_started"

        scoring = curr.scoring_play(prev)
        if scoring:
            team, points = scoring
            label = _SCORE_LABELS.get(points, "score")
            return f"{label}:{team}"

        if (prev.possession_home is not None and curr.possession_home is not None
                and prev.possession_home != curr.possession_home):
            return "possession_change"

        if (prev.down is not None and curr.down is not None
                and curr.down == 1 and prev.down != 1
                and prev.possession_home == curr.possession_home):
            return "first_down"

        return "drift"

    def _team_label(self, home_or_away):
        return self.home_abbr if home_or_away == "home" else self.away_abbr

    def _possessor_label(self, state):
        if state.possession_home is True:
            return self.home_abbr
        if state.possession_home is False:
            return self.away_abbr
        return "Offense"

    def _format_message(self, wp_before, wp_after, event_type, state):
        pct_before, pct_after = wp_before * 100, wp_after * 100
        swing = abs(pct_after - pct_before)
        arrow = "UP" if wp_after >= wp_before else "DOWN"
        beneficiary = self.home_abbr if wp_after >= wp_before else self.away_abbr

        if ":" in event_type:
            label, team = event_type.split(":")
            headline = f"{self._team_label(team)} {label.replace('_', ' ')}"
        elif event_type == "kickoff":
            headline = "Kickoff"
        elif event_type == "tracking_started":
            headline = "Tracking started"
        elif event_type == "possession_change":
            headline = "Possession change (turnover or punt)"
        elif event_type == "first_down":
            headline = f"{self._possessor_label(state)} converts a first down"
        else:
            headline = "Field position / game-clock shift"

        return (f"{headline}: {self.home_abbr} win probability {pct_before:.0f}% -> "
                f"{pct_after:.0f}%  ({arrow} {swing:.0f} pts, favors {beneficiary})")
