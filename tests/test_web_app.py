import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from src.elo import EloRatings
from web import app as web_app


@pytest.fixture
def client(monkeypatch):
    web_app.app.testing = True
    # keep tests off the network / real Elo bootstrap: a flat 1500-rated league
    monkeypatch.setattr(web_app, "_elo", EloRatings({"KC": 1500.0, "SF": 1500.0}))
    return web_app.app.test_client()


def test_index_serves_dashboard(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"NFLTrader" in resp.data


def test_status_reflects_a_fresh_portfolio(client, monkeypatch):
    monkeypatch.setattr(web_app.PaperBroker, "load", classmethod(lambda cls, path=None: cls()))
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["summary"]["bankroll"] == pytest.approx(1000.0)
    assert body["open_positions"] == []


def _summary(state="in", plays=()):
    return {
        "header": {"competitions": [{
            "date": "2026-09-27T17:00Z",
            "status": {"period": 2, "displayClock": "5:00",
                       "type": {"state": state, "completed": state == "post", "shortDetail": "2nd 5:00"}},
            "situation": {"possession": "12", "down": 1, "distance": 10, "yardLine": 40,
                          "downDistanceText": "1st & 10 at SF 40"},
            "competitors": [
                {"homeAway": "home", "score": "10",
                 "team": {"id": "12", "abbreviation": "KC", "displayName": "Kansas City Chiefs"}},
                {"homeAway": "away", "score": "3",
                 "team": {"id": "25", "abbreviation": "SF", "displayName": "San Francisco 49ers"}},
            ],
        }]},
        "drives": {"previous": [{"plays": list(plays)}]},
    }


def _play(pid, text, home, away, quarter=1, clock="10:00", scoring=False, offense="12"):
    return {"id": pid, "text": text, "type": {"text": "Rush"}, "homeScore": home, "awayScore": away,
            "period": {"number": quarter}, "clock": {"displayValue": clock}, "scoringPlay": scoring,
            "start": {"team": {"id": offense}, "downDistanceText": "1st & 10 at KC 25"},
            "end": {"team": {"id": offense}, "yardsToEndzone": 60}}


def test_game_requires_event_id(client):
    resp = client.get("/api/game")
    assert resp.status_code == 400


def test_game_502s_when_espn_fails(client, monkeypatch):
    def boom(event_id):
        raise RuntimeError("ESPN down")
    monkeypatch.setattr(web_app.espn_feed, "read_summary", boom)
    resp = client.get("/api/game?event_id=1")
    assert resp.status_code == 502
    assert "ESPN down" in resp.get_json()["error"]


def test_game_returns_play_by_play_with_win_prob_swings(client, monkeypatch):
    plays = [_play("1", "P.Mahomes 12 yd run", 0, 0),
             _play("2", "P.Mahomes pass to T.Kelce for TD", 7, 0, clock="6:00", scoring=True)]
    monkeypatch.setattr(web_app.espn_feed, "read_summary", lambda event_id: _summary(plays=plays))

    body = client.get("/api/game?event_id=1").get_json()
    assert body["state"] == "in"
    assert body["home"]["abbr"] == "KC" and body["home"]["score"] == 10
    assert body["down_distance"] == "1st & 10 at SF 40"
    assert [p["text"] for p in body["plays"]] == ["P.Mahomes 12 yd run", "P.Mahomes pass to T.Kelce for TD"]
    td = body["plays"][1]
    assert td["scoring"] and td["wp_delta"] > 0          # a home TD moves home win prob up
    assert td["wp_home"] == pytest.approx(body["plays"][0]["wp_home"] + td["wp_delta"])
    assert 0.0 <= body["win_prob_home"] <= 1.0


def test_pregame_game_uses_elo_pick_and_has_no_plays(client, monkeypatch):
    monkeypatch.setattr(web_app.espn_feed, "read_summary", lambda event_id: _summary(state="pre"))
    body = client.get("/api/game?event_id=1").get_json()
    assert body["state"] == "pre"
    assert body["plays"] == []
    assert body["win_prob_home"] == pytest.approx(body["pregame_home_prob"])
    assert body["win_prob_home"] > 0.5                   # home-field edge in an even matchup


def test_scoreboard_attaches_pregame_pick(client, monkeypatch):
    monkeypatch.setattr(web_app.espn_feed, "list_games", lambda: [
        {"event_id": "1", "home_abbr": "KC", "away_abbr": "SF", "state": "pre"}])
    games = client.get("/api/scoreboard").get_json()
    assert 0.5 < games[0]["pregame_home_prob"] < 1.0
