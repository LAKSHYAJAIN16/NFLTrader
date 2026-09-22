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


def test_espn_abbrs_map_to_elo_history():
    assert espn_feed.to_elo_abbr("WSH") == "WAS"
    assert espn_feed.to_elo_abbr("LAR") == "LA"
    assert espn_feed.to_elo_abbr("BUF") == "BUF"


def _event(state):
    return {"id": "1", "date": "2026-09-27T17:00Z", "status": {"type": {"state": state, "shortDetail": "x"}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "score": "0", "team": {"abbreviation": "BUF"}},
                {"homeAway": "away", "score": "0", "team": {"abbreviation": "LAC"}}]}]}


def test_slate_looks_ahead_once_the_week_is_final(monkeypatch):
    calls = []

    def fake(params=None):
        calls.append(params)
        if params is None:
            return {"week": {"number": 2}, "season": {"type": 2}, "events": [_event("post")]}
        return {"events": [_event("pre")]}
    monkeypatch.setattr(espn_feed, "_fetch_scoreboard", fake)

    games = espn_feed.list_games()
    assert calls[1] == {"week": 3, "seasontype": 2}
    assert games[0]["state"] == "pre" and games[0]["kickoff"] == "2026-09-27T17:00Z"


def test_slate_stays_on_a_week_with_games_left(monkeypatch):
    calls = []

    def fake(params=None):
        calls.append(params)
        return {"week": {"number": 3}, "season": {"type": 2}, "events": [_event("post"), _event("pre")]}
    monkeypatch.setattr(espn_feed, "_fetch_scoreboard", fake)

    assert len(espn_feed.list_games()) == 2
    assert calls == [None]


def test_plays_flatten_drives_and_track_possession_after_the_play():
    summary = dict(LIVE_SUMMARY, drives={"previous": [{"plays": [
        {"id": "1", "text": " J.Bates kicks 65 yards ", "type": {"text": "Kickoff"},
         "homeScore": 0, "awayScore": 0, "period": {"number": 1}, "clock": {"displayValue": "15:00"},
         "start": {"team": {"id": "8"}}, "end": {"team": {"id": "2"}, "yardsToEndzone": 75}},
    ]}], "current": {"plays": [
        {"id": "2", "text": "J.Allen pass for 9", "type": {"text": "Pass Reception"},
         "homeScore": 0, "awayScore": 0, "period": {"number": 1}, "clock": {"displayValue": "14:51"},
         "start": {"team": {"id": "2"}, "downDistanceText": "1st & 10 at BUF 25"},
         "end": {"team": {"id": "2"}, "yardsToEndzone": 66}},
    ]}})
    plays = espn_feed.plays_from_summary(summary)
    assert [p["id"] for p in plays] == ["1", "2"]
    kickoff = plays[0]
    assert kickoff["text"] == "J.Bates kicks 65 yards"
    assert kickoff["offense_home"] is False and kickoff["possession_home"] is True
    assert plays[1]["clock_seconds"] == 14 * 60 + 51
    assert plays[1]["down_distance"] == "1st & 10 at BUF 25"


def _pbp(*plays):
    return dict(LIVE_SUMMARY, drives={"previous": [{"plays": list(plays)}]})


def _p(pid, type_, home, away, offense, scoring=False, end_team=None, ytez=None):
    return {"id": pid, "text": pid, "type": {"text": type_}, "scoringPlay": scoring,
            "homeScore": home, "awayScore": away, "period": {"number": 1}, "clock": {"displayValue": "9:09"},
            "start": {"team": {"id": offense}}, "end": {"team": {"id": end_team or offense}, "yardsToEndzone": ytez}}


def test_after_a_score_the_other_side_is_due_the_ball():
    plays = espn_feed.plays_from_summary(_pbp(
        _p("run", "Rush", 0, 0, "2", ytez=5),
        _p("td", "Rushing Touchdown", 7, 0, "2", scoring=True, ytez=0),
    ))
    td = plays[1]
    assert td["offense_home"] is True
    assert td["possession_home"] is False                     # DET receives the kickoff
    assert td["yards_to_endzone"] == espn_feed.POST_SCORE_YARDS_TO_ENDZONE


def test_after_a_safety_the_scorer_gets_the_ball():
    plays = espn_feed.plays_from_summary(_pbp(
        _p("sfty", "Safety", 0, 2, "2", scoring=True, ytez=100),
    ))
    assert plays[0]["possession_home"] is False                # away (DET) scored 2 and receives


def test_timeouts_keep_the_previous_field_state():
    plays = espn_feed.plays_from_summary(_pbp(
        _p("run", "Rush", 0, 0, "2", ytez=40),
        _p("to", "Timeout", 0, 0, "8", end_team="8", ytez=0),
    ))
    assert plays[1]["possession_home"] is True
    assert plays[1]["yards_to_endzone"] == 40
