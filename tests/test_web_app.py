import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from src.elo import EloRatings
from src.scoring_model import Calibration, ScoringModel
from web import app as web_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    web_app.app.testing = True
    for cache in (web_app._summaries, web_app._event_slugs, web_app._market_lists):
        cache.clear()
    # keep tests off the network / real calibration: a flat, even league
    cal = Calibration(margin_slope=1 / 25.0, margin_intercept=0.0, margin_std=13.5,
                      total_mean=45.0, total_std=10.0)
    monkeypatch.setattr(web_app, "_model", ScoringModel(EloRatings({"KC": 1435.0, "SF": 1500.0}), cal))
    # paper portfolio in a temp file, never the real one
    portfolio = str(tmp_path / "portfolio.json")
    monkeypatch.setattr(web_app.PaperBroker, "load", classmethod(lambda cls, path=portfolio: _load(cls, path)))
    monkeypatch.setattr(web_app.PaperBroker, "save", lambda self, path=portfolio: _save(self, path))
    monkeypatch.setattr(web_app.PaperBroker, "_log_trade", lambda self, position, event: None)
    return web_app.app.test_client()


def _load(cls, path):
    if not os.path.exists(path):
        return cls()
    with open(path) as f:
        data = json.load(f)
    return cls(bankroll=data["bankroll"], positions=data["positions"])


def _save(broker, path):
    with open(path, "w") as f:
        json.dump({"bankroll": broker.bankroll, "positions": broker.positions}, f)


def test_index_serves_dashboard(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"NFLTrader" in resp.data


def test_status_reflects_a_fresh_portfolio(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["summary"]["bankroll"] == pytest.approx(1000.0)
    assert body["open_positions"] == []


def _summary(state="in", plays=(), home_score="10", away_score="3", linescores=None):
    linescores = linescores or [(7, 3), (3, 0)]
    return {
        "header": {"competitions": [{
            "date": "2026-09-27T17:00Z",
            "status": {"period": 2, "displayClock": "5:00",
                       "type": {"state": state, "completed": state == "post", "shortDetail": "2nd 5:00"}},
            "situation": {"possession": "12", "down": 1, "distance": 10, "yardLine": 40,
                          "downDistanceText": "1st & 10 at SF 40"},
            "competitors": [
                {"homeAway": "home", "score": home_score,
                 "linescores": [{"displayValue": str(h)} for h, _ in linescores],
                 "team": {"id": "12", "abbreviation": "KC", "displayName": "Kansas City Chiefs"}},
                {"homeAway": "away", "score": away_score,
                 "linescores": [{"displayValue": str(a)} for _, a in linescores],
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
    # late and close, where a score should clearly move the needle
    plays = [_play("1", "P.Mahomes 12 yd run", 17, 17, quarter=4, clock="3:00"),
             _play("2", "P.Mahomes pass to T.Kelce for TD", 24, 17, quarter=4, clock="2:10", scoring=True)]
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
    assert body["win_prob_home"] == pytest.approx(0.5, abs=0.01)   # fixture league: even after home field


def test_scoreboard_attaches_pregame_pick(client, monkeypatch):
    monkeypatch.setattr(web_app.espn_feed, "list_games", lambda: [
        {"event_id": "1", "home_abbr": "KC", "away_abbr": "SF", "state": "pre"}])
    games = client.get("/api/scoreboard").get_json()
    assert games[0]["pregame_home_prob"] == pytest.approx(0.5, abs=0.01)


# ---- markets & paper trading ----

POLY_TEAMS = ({"abbr": "KC", "alias": "Chiefs", "name": "Kansas City Chiefs"},
              {"abbr": "SF", "alias": "49ers", "name": "San Francisco 49ers"})


def _market(mid, smt, question, outcomes, prices, asks=None, volume=10_000.0, closed=False,
            title=None, slug="nfl-sf-kc-2026-09-27"):
    return {"market_id": mid, "question": question, "group_item_title": title, "sports_market_type": smt,
            "outcomes": outcomes, "prices": prices, "asks": asks or prices, "volume": volume,
            "closed": closed, "active": True, "game_start": "2026-09-27 17:00:00+00", "event_slug": slug}


def _board(monkeypatch, summary, markets):
    monkeypatch.setattr(web_app.espn_feed, "read_summary", lambda event_id: summary)
    monkeypatch.setattr(web_app.polymarket_client, "find_game_event_slugs",
                        lambda home, away, kickoff: ["nfl-sf-kc-2026-09-27"])
    monkeypatch.setattr(web_app.polymarket_client, "get_game_markets",
                        lambda slugs: (POLY_TEAMS[0], POLY_TEAMS[1], list(markets)))


def _pregame_markets():
    return [
        _market("ml", "moneyline", "49ers vs. Chiefs", ["49ers", "Chiefs"], [0.30, 0.70], asks=[0.31, 0.71]),
        _market("tot", "totals", "O/U 44.5", ["Over", "Under"], [0.30, 0.70], title="O/U 44.5"),
        _market("thin", "totals", "O/U 50.5", ["Over", "Under"], [0.30, 0.70], title="O/U 50.5", volume=20.0),
        _market("prop", "player_passing_yards", "Mahomes O/U 275.5 yds", ["Over", "Under"], [0.5, 0.5],
                slug="nfl-sf-kc-2026-09-27-player-props"),
    ]


def test_markets_price_every_market_and_flag_what_they_cant(client, monkeypatch):
    _board(monkeypatch, _summary(state="pre"), _pregame_markets())
    body = client.get("/api/markets?event_id=1").get_json()
    assert body["available"] and body["pricing"] == "pregame"
    by_id = {m["id"]: m for m in body["markets"]}
    assert set(by_id) == {"ml", "tot", "thin", "prop"}

    # even matchup vs. a 71c ask on KC: model says ~50%, so the edge is on SF at 31c
    sf, kc = by_id["ml"]["outcomes"]
    assert sf["model"] == pytest.approx(0.5, abs=0.02) and sf["edge"] > 0.15 and sf["stake"] > 0
    assert kc["edge"] < 0 and kc["stake"] == 0

    assert by_id["tot"]["outcomes"][0]["stake"] > 0             # Over 44.5 at 30c vs ~50%
    assert not by_id["thin"]["liquid"] and by_id["thin"]["outcomes"][0]["stake"] == 0
    assert by_id["thin"]["best_edge"] is None
    prop = by_id["prop"]
    assert not prop["modeled"] and prop["group"] == "Player props"
    assert all(o["model"] is None for o in prop["outcomes"])


def test_markets_reprice_live_from_the_scoreboard(client, monkeypatch):
    # 49 already on the board at half: Over 44.5 is all but won
    summary = _summary(state="in", home_score="28", away_score="21", linescores=[(14, 7), (14, 14)])
    _board(monkeypatch, summary, _pregame_markets())
    body = client.get("/api/markets?event_id=1").get_json()
    assert body["pricing"] == "live"
    over = next(m for m in body["markets"] if m["id"] == "tot")["outcomes"][0]
    assert over["model"] > 0.99


def test_markets_when_polymarket_has_no_event(client, monkeypatch):
    monkeypatch.setattr(web_app.espn_feed, "read_summary", lambda event_id: _summary(state="pre"))
    monkeypatch.setattr(web_app.polymarket_client, "find_game_event_slugs", lambda *a: [])
    body = client.get("/api/markets?event_id=1").get_json()
    assert body["available"] is False and body["markets"] == []


def test_paper_trade_fills_at_the_ask_with_the_suggested_stake(client, monkeypatch):
    _board(monkeypatch, _summary(state="pre"), _pregame_markets())
    resp = client.post("/api/trade", json={"event_id": "1", "market_id": "ml", "outcome": 0})
    assert resp.status_code == 200, resp.get_json()
    pos = resp.get_json()["position"]
    assert pos["side_team"] == "49ers" and pos["entry_price"] == pytest.approx(0.31)
    assert pos["stake"] > 0
    assert resp.get_json()["portfolio"]["bankroll"] == pytest.approx(1000.0 - pos["stake"])

    board = client.get("/api/markets?event_id=1").get_json()
    held = next(m for m in board["markets"] if m["id"] == "ml")["position"]
    assert held["side_team"] == "49ers" and "unrealized" in held
    assert len(board["positions"]) == 1

    again = client.post("/api/trade", json={"event_id": "1", "market_id": "ml", "outcome": 0})
    assert again.status_code == 409


def test_trade_without_edge_needs_an_explicit_stake(client, monkeypatch):
    _board(monkeypatch, _summary(state="pre"), _pregame_markets())
    no_edge = client.post("/api/trade", json={"event_id": "1", "market_id": "ml", "outcome": 1})
    assert no_edge.status_code == 400
    manual = client.post("/api/trade", json={"event_id": "1", "market_id": "prop", "outcome": 0, "stake": 10})
    assert manual.status_code == 200
    assert manual.get_json()["position"]["model_prob"] is None


def test_final_game_settles_quarter_and_prop_positions(client, monkeypatch):
    markets = _pregame_markets() + [
        _market("q1", "q1_moneyline", "Q1 winner", ["49ers", "Chiefs"], [0.5, 0.5])]
    _board(monkeypatch, _summary(state="pre"), markets)
    assert client.post("/api/trade", json={"event_id": "1", "market_id": "q1", "outcome": 1,
                                           "stake": 20}).status_code == 200
    assert client.post("/api/trade", json={"event_id": "1", "market_id": "prop", "outcome": 0,
                                           "stake": 10}).status_code == 200

    # final: KC won Q1 7-3; Polymarket has resolved the prop to Under
    resolved = [dict(m) for m in markets]
    for m in resolved:
        if m["market_id"] == "prop":
            m.update(closed=True, prices=[0.0, 1.0])
    for cache in (web_app._summaries, web_app._market_lists):
        cache.clear()
    final = _summary(state="post", home_score="24", away_score="20",
                     linescores=[(7, 3), (3, 7), (7, 3), (7, 7)])
    _board(monkeypatch, final, resolved)

    body = client.get("/api/markets?event_id=1").get_json()
    status = {p["market_id"]: p for p in body["positions"]}
    assert status["q1"]["status"] == "settled" and status["q1"]["won"] is True
    assert status["prop"]["status"] == "settled" and status["prop"]["won"] is False
    assert body["portfolio"]["settled_bets"] == 2
