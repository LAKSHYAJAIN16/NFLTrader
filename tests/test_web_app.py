import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from src.cv.game_state import GameState
from web import app as web_app


@pytest.fixture
def client():
    web_app.app.testing = True
    web_app._live_games.clear()
    web_app._event_ids.clear()
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


def test_game_requires_both_teams(client):
    resp = client.get("/api/game?home=KC")
    assert resp.status_code == 400


def test_game_404s_when_espn_has_no_such_matchup(client, monkeypatch):
    monkeypatch.setattr(web_app.espn_feed, "find_event_id", lambda home, away: None)
    resp = client.get("/api/game?home=KC&away=SF")
    assert resp.status_code == 404


def test_game_polls_and_returns_win_probability(client, monkeypatch):
    monkeypatch.setattr(web_app.espn_feed, "find_event_id", lambda home, away: "12345")
    state = GameState(home_score=10, away_score=3, quarter=2, clock_seconds=300,
                       possession_home=True, down=1, distance=10, yard_line=40)
    monkeypatch.setattr(web_app.espn_feed, "read_game_state", lambda event_id, home, away: state)

    resp = client.get("/api/game?home=KC&away=SF")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["home_score"] == 10
    assert body["away_score"] == 3
    assert 0.0 <= body["win_prob_home"] <= 1.0
    assert body["win_prob_home"] + body["win_prob_away"] == pytest.approx(1.0)
    assert len(body["history"]) == 1

    # a second poll of the same matchup should accumulate history, not reset it
    resp2 = client.get("/api/game?home=KC&away=SF")
    assert len(resp2.get_json()["history"]) == 2
