"""Runs the win-probability InsightEngine over a scripted sequence of
GameStates - no video/CV required - so you can see the insight narration
working end to end without a broadcast feed to point the reader at.

Usage: python tools/demo_insights.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cv.game_state import GameState
from src.insights import InsightEngine

# A scripted 4th-quarter sequence for a fictional KC (home) vs SF (away) game:
# SF leads 24-20 with 6:00 left, drives into KC territory, throws a pick-six.
SCRIPT = [
    GameState(home_score=20, away_score=24, quarter=4, clock_seconds=360,
              possession_home=False, down=1, distance=10, yard_line=75),
    GameState(home_score=20, away_score=24, quarter=4, clock_seconds=330,
              possession_home=False, down=1, distance=10, yard_line=58),
    GameState(home_score=20, away_score=24, quarter=4, clock_seconds=300,
              possession_home=False, down=2, distance=3, yard_line=51),
    # interception returned for a touchdown: possession AND score flip in one read
    GameState(home_score=27, away_score=24, quarter=4, clock_seconds=280,
              possession_home=False, down=1, distance=10, yard_line=75),
    GameState(home_score=27, away_score=24, quarter=4, clock_seconds=120,
              possession_home=True, down=3, distance=2, yard_line=40),
    GameState(home_score=27, away_score=24, quarter=4, clock_seconds=90,
              possession_home=True, down=1, distance=10, yard_line=30),
]


def main():
    engine = InsightEngine(pregame_home_prob=0.55, home_abbr="KC", away_abbr="SF")
    print(f"Pregame model: KC {engine.win_prob:.0%}\n")
    for state in SCRIPT:
        insight = engine.process(state)
        if insight:
            print(f"[{state.quarter}Q {state.clock_seconds // 60}:{state.clock_seconds % 60:02d}] "
                  f"{insight.message}")
    print(f"\nFinal model win probability: KC {engine.win_prob:.0%}")


if __name__ == "__main__":
    main()
