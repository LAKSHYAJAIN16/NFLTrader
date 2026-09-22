import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import espn_feed

# A trimmed fixture shaped like ESPN's summary endpoint response for a live game.
LIVE_SUMMARY = {
    "header": {
        "competitions": [{
            "status": {"period": 3, "displayClock": "7:42"},
            "situation": {"down": 2, "distance": 6, "yardLine": 35, "possession": "2"},
            "competitors": [
                {"id": "2", "homeAway": "home", "score": "17",
                 "team": {"id": "2", "abbreviation": "BUF"}},
                {"id": "8", "homeAway": "away", "score": "14",
                 "team": {"id": "8", "abbreviation": "DET"}},
            ],
        }]
    }
}

PREGAME_SUMMARY = {
    "header": {
        "competitions": [{
            "status": {"period": 0, "displayClock": "0:00"},
            "situation": {},
            "competitors": [
                {"id": "2", "homeAway": "home", "score": "0",
                 "team": {"id": "2", "abbreviation": "BUF"}},
                {"id": "8", "homeAway": "away", "score": "0",
                 "team": {"id": "8", "abbreviation": "DET"}},
            ],
        }]
    }
}


def test_parses_scores_and_clock():
    state = espn_feed._state_from_summary(LIVE_SUMMARY, "BUF", "DET")
    assert state.home_score == 17
    assert state.away_score == 14
    assert state.quarter == 3
    assert state.clock_seconds == 7 * 60 + 42


def test_parses_down_distance_and_field_position():
    state = espn_feed._state_from_summary(LIVE_SUMMARY, "BUF", "DET")
    assert state.down == 2
    assert state.distance == 6
    assert state.yard_line == 35


def test_possession_resolved_against_home_team_id():
    state = espn_feed._state_from_summary(LIVE_SUMMARY, "BUF", "DET")
    assert state.possession_home is True  # possession team id "2" == BUF's id


def test_pregame_degrades_gracefully():
    state = espn_feed._state_from_summary(PREGAME_SUMMARY, "BUF", "DET")
    assert state.home_score == 0
    assert state.down is None
    assert state.possession_home is None
    assert state.is_plausible()


def test_changed_ignores_timestamp_only_diffs():
    a = espn_feed._state_from_summary(LIVE_SUMMARY, "BUF", "DET", timestamp=1.0)
    b = espn_feed._state_from_summary(LIVE_SUMMARY, "BUF", "DET", timestamp=2.0)
    assert espn_feed._changed(a, b) is False


def test_changed_true_when_score_moves():
    a = espn_feed._state_from_summary(PREGAME_SUMMARY, "BUF", "DET")
    b = espn_feed._state_from_summary(LIVE_SUMMARY, "BUF", "DET")
    assert espn_feed._changed(a, b) is True


FINAL_SUMMARY = {
    "header": {
        "competitions": [{
            "status": {"type": {"state": "post", "completed": True, "detail": "Final"}},
            "competitors": [
                {"id": "2", "homeAway": "home", "score": "41",
                 "team": {"id": "2", "abbreviation": "BUF"}},
                {"id": "8", "homeAway": "away", "score": "31",
                 "team": {"id": "8", "abbreviation": "DET"}},
            ],
        }]
    }
}


def test_final_game_reports_end_of_regulation_not_q1():
    # ESPN omits period/displayClock on final games
    state = espn_feed._state_from_summary(FINAL_SUMMARY, "BUF", "DET")
    assert state.quarter == 4
    assert state.clock_seconds == 0


def test_final_ot_game_reports_overtime():
    summary = {"header": {"competitions": [dict(FINAL_SUMMARY["header"]["competitions"][0],
                                                status={"type": {"completed": True, "detail": "Final/OT"}})]}}
    state = espn_feed._state_from_summary(summary, "BUF", "DET")
    assert state.quarter == 5
    assert state.clock_seconds == 0
