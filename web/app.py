"""Local web dashboard for NFLTrader.

Serves the same live win-probability model, insight narration, and paper
portfolio the CLI uses, over a small JSON API plus one static page - no
build step, no new state format, no real money anywhere here either.

Run with `python main.py web` (or `python web/app.py` directly), then open
http://127.0.0.1:5000 in a browser. This is a local Flask dev server only -
it is not deployed anywhere, so it's reachable exclusively from the machine
it's running on (or another machine on the same network if you pass
--host 0.0.0.0). See README.md for details.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, send_from_directory

from src import espn_feed, insights
from src.elo import EloRatings
from src.paper_broker import PaperBroker

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_HISTORY_POINTS = 200

app = Flask(__name__, static_folder=None)

_elo = None
_live_games = {}   # (home_abbr, away_abbr) -> _LiveGame
_event_ids = {}    # (home_abbr, away_abbr) -> ESPN event id


class _LiveGame:
    """Holds the one running InsightEngine + win-prob history for a given
    matchup so repeated polls narrate deltas instead of recomputing cold
    each time - mirrors what `main.py live` does in a single process."""

    def __init__(self, home_abbr, away_abbr, pregame_home_prob):
        self.engine = insights.InsightEngine(pregame_home_prob, home_abbr=home_abbr, away_abbr=away_abbr)
        self.history = []  # [{"t": epoch_seconds, "wp": home_win_prob}, ...]

    def poll(self, event_id, home_abbr, away_abbr):
        state = espn_feed.read_game_state(event_id, home_abbr, away_abbr)
        insight = self.engine.process(state)
        self.history.append({"t": time.time(), "wp": self.engine.win_prob})
        del self.history[:-MAX_HISTORY_POINTS]
        return state, insight


def _get_elo():
    global _elo
    if _elo is None:
        _elo = EloRatings.load()
    return _elo


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/api/scoreboard")
def api_scoreboard():
    try:
        return jsonify(espn_feed.list_games())
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.get("/api/game")
def api_game():
    home = (request.args.get("home") or "").upper()
    away = (request.args.get("away") or "").upper()
    if not home or not away:
        return jsonify({"error": "home and away query params are required"}), 400
    key = (home, away)

    if key not in _event_ids:
        try:
            event_id = espn_feed.find_event_id(home, away)
        except Exception as e:
            return jsonify({"error": str(e)}), 502
        if not event_id:
            return jsonify({"error": f"No {away} @ {home} game found on ESPN's current scoreboard"}), 404
        _event_ids[key] = event_id

    if key not in _live_games:
        pregame_home_prob = _get_elo().expected_home_win_prob(home, away)
        _live_games[key] = _LiveGame(home, away, pregame_home_prob)
    game = _live_games[key]

    try:
        state, insight = game.poll(_event_ids[key], home, away)
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    return jsonify({
        "home_abbr": home,
        "away_abbr": away,
        "home_score": state.home_score,
        "away_score": state.away_score,
        "quarter": state.quarter,
        "clock_seconds": state.clock_seconds,
        "possession_home": state.possession_home,
        "win_prob_home": game.engine.win_prob,
        "win_prob_away": 1 - game.engine.win_prob,
        "insight": insight.message if insight else None,
        "history": game.history,
    })


@app.get("/api/status")
def api_status():
    broker = PaperBroker.load()
    positions = [
        {
            "question": p["question"],
            "side_team": p["side_team"],
            "entry_price": p["entry_price"],
            "stake": p["stake"],
            "model_prob": p.get("model_prob"),
            "market_prob": p.get("market_prob"),
        }
        for p in broker.open_positions()
    ]
    return jsonify({"summary": broker.summary(), "open_positions": positions})


def create_app():
    return app


def run(host="127.0.0.1", port=5000, debug=False):
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run(debug=True)
