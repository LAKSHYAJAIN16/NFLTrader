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
    timestamp: Optional[float] = None  # video timestamp (sec) this was read at

    def is_plausible(self, prev: Optional["GameState"] = None) -> bool:
        """Basic sanity checks so a garbled OCR read doesn't corrupt the state."""
        if not (0 <= self.home_score <= 100 and 0 <= self.away_score <= 100):
            return False
        if not (1 <= self.quarter <= 6):
            return False
        if not (0 <= self.clock_seconds <= 15 * 60):
            return False
        if prev is not None:
            # scores should never decrease
            if self.home_score < prev.home_score or self.away_score < prev.away_score:
                return False
        return True
