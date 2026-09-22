"""Local web dashboard for NFLTrader.

Serves the same live win-probability model, ESPN play-by-play, and paper
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, send_from_directory

from src import data_loader, espn_feed, win_probability
from src.elo import EloRatings
from src.paper_broker import PaperBroker

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = Flask(__name__, static_folder=None)

_elo = None


def _get_elo():
    """Same first-run bootstrap as the CLI: without it every matchup would read
    as a coin flip plus home-field edge."""
    global _elo
    if _elo is None:
        _elo = EloRatings.load()
        if not _elo.ratings:
            data_loader.bootstrap_elo(_elo)
            _elo.save()
    return _elo


def _pregame_home_prob(home_abbr, away_abbr):
    return _get_elo().expected_home_win_prob(espn_feed.to_elo_abbr(home_abbr),
                                             espn_feed.to_elo_abbr(away_abbr))


def _with_win_prob(plays, pregame_home_prob):
    """Annotates each play with the model's home win probability after it and
    the swing from the play before - the same model `main.py live` runs."""
    wp_before = pregame_home_prob
    for play in plays:
        wp = win_probability.live_home_win_prob(
            pregame_home_prob, play["home_score"], play["away_score"],
            play["quarter"], play["clock_seconds"],
            play["possession_home"], play["yards_to_endzone"],
        )
        play["wp_home"] = wp
        play["wp_delta"] = wp - wp_before
        play["minor"] = play["type"] in espn_feed.NON_ACTION_PLAY_TYPES
        wp_before = wp
    return plays


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/api/scoreboard")
def api_scoreboard():
    try:
        games = espn_feed.list_games()
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    for g in games:
        g["pregame_home_prob"] = _pregame_home_prob(g["home_abbr"], g["away_abbr"])
    return jsonify(games)


@app.get("/api/game")
def api_game():
    event_id = request.args.get("event_id", "").strip()
    if not event_id:
        return jsonify({"error": "event_id query param is required"}), 400

    try:
        summary = espn_feed.read_summary(event_id)
        teams = espn_feed.teams_from_summary(summary)
        home, away = teams["home"], teams["away"]
        state = espn_feed._state_from_summary(summary, home["abbr"], away["abbr"])
        plays = espn_feed.plays_from_summary(summary)
    except Exception as e:
        return jsonify({"error": f"Couldn't read game {event_id} from ESPN: {e}"}), 502

    comp = summary["header"]["competitions"][0]
    status_type = comp["status"].get("type", {})
    game_state = status_type.get("state", "pre")

    pregame = _pregame_home_prob(home["abbr"], away["abbr"])
    _with_win_prob(plays, pregame)
    if game_state == "pre":
        win_prob_home = pregame
    else:
        win_prob_home = win_probability.live_home_win_prob(
            pregame, state.home_score, state.away_score, state.quarter,
            state.clock_seconds, state.possession_home, state.yard_line,
        )

    return jsonify({
        "event_id": event_id,
        "state": game_state,
        "status": status_type.get("shortDetail", ""),
        "kickoff": comp.get("date"),
        "home": home,
        "away": away,
        "quarter": state.quarter,
        "clock_seconds": state.clock_seconds,
        "possession_home": state.possession_home,
        "down_distance": comp.get("situation", {}).get("downDistanceText"),
        "pregame_home_prob": pregame,
        "win_prob_home": win_prob_home,
        "plays": plays,
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
