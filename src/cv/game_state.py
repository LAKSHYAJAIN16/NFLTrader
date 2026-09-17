"""The structured game state extracted from a broadcast frame."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class GameState:
    home_score: int
    away_score: int
    quarter: int
    clock_seconds: int          # seconds remaining in the current quarter
    possession_home: Optional[bool] = None
    down: Optional[int] = None
    distance: Optional[int] = None
    yard_line: Optional[int] = None  # yards to the possessing team's target end zone, 0-100
    timestamp: Optional[float] = None  # video timestamp (sec) this was read at

    def is_plausible(self, prev: Optional["GameState"] = None) -> bool:
        """Basic sanity checks so a garbled OCR read doesn't corrupt the state."""
        if not (0 <= self.home_score <= 100 and 0 <= self.away_score <= 100):
            return False
        if not (1 <= self.quarter <= 6):
            return False
        if not (0 <= self.clock_seconds <= 15 * 60):
            return False
        if self.down is not None and not (1 <= self.down <= 4):
            return False
        if self.yard_line is not None and not (0 <= self.yard_line <= 100):
            return False
        if prev is not None:
            # scores should never decrease
            if self.home_score < prev.home_score or self.away_score < prev.away_score:
                return False
        return True

    def scoring_play(self, prev: Optional["GameState"]) -> Optional[tuple]:
        """Returns (team, points) for the team that just scored since `prev`, or None."""
        if prev is None:
            return None
        home_gain = self.home_score - prev.home_score
        away_gain = self.away_score - prev.away_score
        if home_gain > 0 and away_gain == 0:
            return ("home", home_gain)
        if away_gain > 0 and home_gain == 0:
            return ("away", away_gain)
        return None
