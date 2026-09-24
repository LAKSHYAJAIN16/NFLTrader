"""Local web dashboard for NFLTrader.

Serves the same live win-probability model, ESPN play-by-play, Polymarket
market pricing, and paper portfolio the CLI uses, over a small JSON API plus
one static page - no build step, no new state format, no real money anywhere
here either: every trade placed from the dashboard is a PaperBroker position.

Run with `python main.py web` (or `python web/app.py` directly), then open
http://127.0.0.1:5000 in a browser. This is a local Flask dev server only -
it is not deployed anywhere, so it's reachable exclusively from the machine
it's running on (or another machine on the same network if you pass
--host 0.0.0.0). See README.md for details.
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, send_from_directory

import config
from src import espn_feed, market_catalog, polymarket_client, strategy, win_probability
from src import scoring_model as sm
from src.paper_broker import PaperBroker

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = Flask(__name__, static_folder=None)

PERIOD_LABELS = {"full": "Full game", "1H": "1st half", "2H": "2nd half",
                 "Q1": "1st quarter", "Q2": "2nd quarter", "Q3": "3rd quarter", "Q4": "4th quarter"}
FAMILY_GROUPS = {"moneyline": "Moneyline", "spread": "Spread", "total": "Total",
                 "team_total": "Team total", "margin_bucket": "Exact margin"}
SIBLING_GROUPS = {"-player-props": "Player props", "-first-td-scorer": "First TD scorer",
                  "-highest-scoring-quarter": "Highest-scoring quarter"}
GROUP_ORDER = ["Moneyline", "Spread", "Total", "Team total", "Exact margin",
               "Game props", "Player props", "First TD scorer", "Highest-scoring quarter"]

_model = None
_model_lock = threading.Lock()
_broker_lock = threading.Lock()


class _TTLCache:
    """Tiny per-key cache so the page's several polls share one upstream fetch."""

    def __init__(self, ttl_seconds):
        self.ttl = ttl_seconds
        self._items = {}
        self._lock = threading.Lock()

    def get(self, key, fetch, fresh=False):
        with self._lock:
            hit = self._items.get(key)
            if hit and not fresh and hit[0] > time.time():
                return hit[1]
        value = fetch()
        with self._lock:
            self._items[key] = (time.time() + self.ttl, value)
        return value

    def clear(self):
        with self._lock:
            self._items.clear()


_summaries = _TTLCache(3)
_event_slugs = _TTLCache(600)
_market_lists = _TTLCache(8)


def _get_model():
    """Elo + margin/total calibration replayed from history, once per process -
    the same fit `main.py trade-game` prices with."""
    global _model
    with _model_lock:
        if _model is None:
            elo, calibration = sm.calibrate()
            _model = sm.ScoringModel(elo, calibration)
    return _model


def _model_abbrs(home_abbr, away_abbr):
    return espn_feed.to_elo_abbr(home_abbr), espn_feed.to_elo_abbr(away_abbr)


def _pregame_home_prob(home_abbr, away_abbr, neutral=False):
    model = _get_model()
    return sm.home_win_prob(model.full_game(*_model_abbrs(home_abbr, away_abbr), neutral=neutral))


def _with_win_prob(plays, pregame_home_prob):
    """Annotates each play with the model's home win probability after it and
    the swing from the play before - the same model `main.py live` runs."""
    margin_std = _get_model().cal.margin_std
    wp_before = pregame_home_prob
    for play in plays:
        wp = win_probability.live_home_win_prob(
            pregame_home_prob, play["home_score"], play["away_score"],
            play["quarter"], play["clock_seconds"],
            play["possession_home"], play["yards_to_endzone"], margin_std=margin_std,
        )
        play["wp_home"] = wp
        play["wp_delta"] = wp - wp_before
        play["minor"] = play["type"] in espn_feed.NON_ACTION_PLAY_TYPES
        wp_before = wp
    return plays


def _game_context(event_id, fresh=False):
    """Everything ESPN says about one game, parsed once per poll."""
    summary = _summaries.get(event_id, lambda: espn_feed.read_summary(event_id), fresh=fresh)
    teams = espn_feed.teams_from_summary(summary)
    home, away = teams["home"], teams["away"]
    comp = summary["header"]["competitions"][0]
    status_type = comp["status"].get("type", {})
    return {
        "event_id": event_id,
        "summary": summary,
        "comp": comp,
        "home": home,
        "away": away,
        "state": espn_feed._state_from_summary(summary, home["abbr"], away["abbr"]),
        "plays": espn_feed.plays_from_summary(summary),
        "quarter_scores": espn_feed.quarter_scores(teams),
        "game_state": status_type.get("state", "pre"),
        "status": status_type.get("shortDetail", ""),
        "kickoff": comp.get("date"),
        "neutral_site": bool(comp.get("neutralSite")),
    }


def _live_state(ctx):
    """LiveState for pricing, or None before kickoff. Field position comes from
    the last real play (more reliable than the header's situation block)."""
    if ctx["game_state"] == "pre":
        return None
    state = ctx["state"]
    last = next((p for p in reversed(ctx["plays"]) if p["type"] not in espn_feed.NON_ACTION_PLAY_TYPES), None)
    return sm.LiveState(
        home_score=state.home_score, away_score=state.away_score,
        quarter=state.quarter, clock_seconds=state.clock_seconds,
        possession_home=last["possession_home"] if last else state.possession_home,
        yards_to_endzone=last["yards_to_endzone"] if last else None,
        quarter_scores=ctx["quarter_scores"],
        final=ctx["game_state"] == "post",
    )


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
        g["pregame_home_prob"] = _pregame_home_prob(g["home_abbr"], g["away_abbr"], g.get("neutral_site", False))
    return jsonify(games)


@app.get("/api/game")
def api_game():
    event_id = request.args.get("event_id", "").strip()
    if not event_id:
        return jsonify({"error": "event_id query param is required"}), 400

    try:
        ctx = _game_context(event_id)
    except Exception as e:
        return jsonify({"error": f"Couldn't read game {event_id} from ESPN: {e}"}), 502

    home, away, state = ctx["home"], ctx["away"], ctx["state"]
    plays = [dict(p) for p in ctx["plays"]]
    pregame = _pregame_home_prob(home["abbr"], away["abbr"], ctx["neutral_site"])
    _with_win_prob(plays, pregame)
    if ctx["game_state"] == "pre":
        win_prob_home = pregame
    else:
        live = _live_state(ctx)
        win_prob_home = win_probability.live_home_win_prob(
            pregame, state.home_score, state.away_score, state.quarter, state.clock_seconds,
            live.possession_home, live.yards_to_endzone, margin_std=_get_model().cal.margin_std,
        )

    return jsonify({
        "event_id": event_id,
        "state": ctx["game_state"],
        "status": ctx["status"],
        "kickoff": ctx["kickoff"],
        "home": home,
        "away": away,
        "quarter": state.quarter,
        "clock_seconds": state.clock_seconds,
        "possession_home": state.possession_home,
        "down_distance": ctx["comp"].get("situation", {}).get("downDistanceText"),
        "pregame_home_prob": pregame,
        "neutral_site": ctx["neutral_site"],
        "win_prob_home": win_prob_home,
        "plays": plays,
    })


# ---------------------------------------------------------------- markets

def _slugs_for(ctx):
    return _event_slugs.get(ctx["event_id"], lambda: polymarket_client.find_game_event_slugs(
        ctx["home"]["name"], ctx["away"]["name"], ctx["kickoff"]))


def _raw_markets(ctx, fresh=False):
    slugs = _slugs_for(ctx)
    if not slugs:
        return None, []
    fetched = _market_lists.get(ctx["event_id"], lambda: polymarket_client.get_game_markets(slugs), fresh=fresh)
    home_info, away_info, markets = fetched
    return (home_info, away_info), markets


def _group_for(raw, family_period):
    if family_period:
        family, period = family_period
        return FAMILY_GROUPS[family], period
    slug = raw.get("event_slug") or ""
    for suffix, group in SIBLING_GROUPS.items():
        if slug.endswith(suffix):
            return group, None
    return "Game props", None


def _price_market(raw, poly_teams, ctx, live, bankroll):
    """One market as the board shows it: every outcome with its market price,
    what buying it costs (the ask), the model's probability where we have a
    model, and the edge / suggested Kelly stake against the ask."""
    home_info, away_info = poly_teams
    family_period = market_catalog.TRADABLE_FAMILIES.get(raw["sports_market_type"])
    specs = market_catalog.parse_market(
        raw["sports_market_type"], raw["question"], raw.get("group_item_title"),
        raw["outcomes"], home_info["alias"], away_info["alias"],
    )
    group, period = _group_for(raw, family_period)
    is_open = bool(raw["active"]) and not raw["closed"]
    liquid = raw["volume"] >= config.MIN_MARKET_VOLUME
    model_home, model_away = _model_abbrs(ctx["home"]["abbr"], ctx["away"]["abbr"])

    threshold, evidence = _suggestion_rule(family_period, live)

    outcomes = []
    for i, name in enumerate(raw["outcomes"]):
        ask = raw["asks"][i] if i < len(raw.get("asks") or []) else raw["prices"][i]
        model_prob = None
        if specs is not None and i < len(specs):
            model_prob = _get_model().price(specs[i][1], model_home, model_away, live, ctx["neutral_site"])
        edge = None if model_prob is None else model_prob - ask
        stake = 0.0
        if threshold is not None and edge is not None and edge >= threshold and liquid and is_open:
            stake = round(strategy.kelly_stake(model_prob, ask, bankroll), 2)
        outcomes.append({"name": name, "price": raw["prices"][i], "ask": ask,
                         "model": model_prob, "edge": edge, "stake": stake,
                         "spec": list(specs[i][1]) if specs is not None and i < len(specs) else None})

    edges = [o["edge"] for o in outcomes if o["edge"] is not None]
    return {
        "id": raw["market_id"],
        "question": raw["question"],
        "title": raw.get("group_item_title") or raw["question"],
        "type": raw["sports_market_type"],
        "group": group,
        "period": period,
        "period_label": PERIOD_LABELS.get(period),
        "volume": raw["volume"],
        "liquid": liquid,
        "open": is_open,
        "modeled": specs is not None,
        "best_edge": max(edges) if edges and liquid and is_open else None,
        "suggested": any(o["stake"] > 0 for o in outcomes),
        "evidence": evidence if specs is not None else None,
        "outcomes": outcomes,
    }


def _suggestion_rule(family_period, live):
    """(edge threshold or None, evidence note) for suggesting a stake on this
    market, per tools/backtest_vs_market.py: pregame the closing line beats the
    model, totals disagreements lose, and spreads only approach break-even at
    very large gaps. Live pricing has no historical market data to test against."""
    family = family_period[0] if family_period else None
    if live is not None:
        return config.EDGE_THRESHOLD, "not_backtested"
    if family in ("total", "team_total") and not config.SUGGEST_PREGAME_TOTALS:
        return None, "totals_lose"
    return config.PREGAME_EDGE_THRESHOLD, "unproven"


def _resolved_outcome(raw):
    """Index of the outcome Polymarket resolved YES, or None if unresolved."""
    if not raw["closed"]:
        return None
    return next((i for i, p in enumerate(raw["prices"]) if p >= 0.99), None)


def _settle_spec(spec, ctx):
    """True/False for a modeled position once the game is final: full-game specs
    from the final score, half/quarter specs from ESPN's linescores."""
    period = spec[-1] if spec[0] in ("win", "cover", "total_over", "total_under",
                                      "team_total_over", "team_total_under") else "full"
    if period == "full":
        return sm.resolve_outcome(tuple(spec), ctx["state"].home_score, ctx["state"].away_score)
    quarters = sm.PERIOD_QUARTERS[period]
    scored = [ctx["quarter_scores"][q - 1] for q in quarters if q <= len(ctx["quarter_scores"])]
    if len(scored) < len(quarters):
        return None
    home_pts, away_pts = sum(h for h, _ in scored), sum(a for _, a in scored)
    return sm.resolve_outcome(tuple(spec[:-1]) + ("full",), home_pts, away_pts)


def _settle_positions(broker, ctx, raw_by_id):
    """Settles this game's open positions: by Polymarket's own resolution when
    the market has resolved (works for props too), else from the final score
    for modeled markets. Returns how many settled."""
    settled = 0
    for position in broker.open_positions():
        if position.get("espn_event_id") != ctx["event_id"]:
            continue
        won = None
        raw = raw_by_id.get(position["market_id"])
        resolved = _resolved_outcome(raw) if raw else None
        if resolved is not None and position.get("outcome_index") is not None:
            won = resolved == position["outcome_index"]
        elif ctx["game_state"] == "post" and position.get("spec"):
            won = _settle_spec(position["spec"], ctx)
        if won is not None:
            broker.settle_outcome(position["market_id"], won)
            settled += 1
    return settled


def _position_view(position, market):
    """An open position marked to the market's current price for its outcome."""
    view = {k: position.get(k) for k in ("market_id", "question", "side_team", "entry_price",
                                          "stake", "shares", "model_prob", "status", "pnl", "won")}
    if market and position.get("outcome_index") is not None and position["status"] == "open":
        now = market["outcomes"][position["outcome_index"]]["price"]
        view["mark"] = now
        view["value"] = position["shares"] * now
        view["unrealized"] = view["value"] - position["stake"]
    return view


@app.get("/api/markets")
def api_markets():
    event_id = request.args.get("event_id", "").strip()
    if not event_id:
        return jsonify({"error": "event_id query param is required"}), 400

    try:
        ctx = _game_context(event_id)
    except Exception as e:
        return jsonify({"error": f"Couldn't read game {event_id} from ESPN: {e}"}), 502
    try:
        poly_teams, raws = _raw_markets(ctx)
    except Exception as e:
        return jsonify({"error": f"Couldn't load Polymarket markets: {e}"}), 502

    with _broker_lock:
        broker = PaperBroker.load()
        if raws:
            if _settle_positions(broker, ctx, {r["market_id"]: r for r in raws}):
                broker.save()

    if not raws:
        return jsonify({"available": False, "state": ctx["game_state"], "markets": [],
                        "groups": [], "portfolio": broker.summary(), "positions": []})

    live = _live_state(ctx)
    markets = [_price_market(r, poly_teams, ctx, live, broker.bankroll) for r in raws]
    by_id = {m["id"]: m for m in markets}
    for m in markets:
        pos = broker.positions.get(m["id"])
        m["position"] = _position_view(pos, m) if pos else None

    game_positions = [_position_view(p, by_id.get(p["market_id"])) for p in broker.positions.values()
                      if p.get("espn_event_id") == event_id]
    game_positions.sort(key=lambda p: (p["status"] != "open", p["question"]))

    groups = sorted({m["group"] for m in markets}, key=lambda g: GROUP_ORDER.index(g) if g in GROUP_ORDER else 99)
    return jsonify({
        "available": True,
        "state": ctx["game_state"],
        "pricing": "pregame" if live is None else ("final" if live.final else "live"),
        "edge_threshold": config.EDGE_THRESHOLD,
        "min_volume": config.MIN_MARKET_VOLUME,
        "groups": groups,
        "markets": markets,
        "portfolio": broker.summary(),
        "positions": game_positions,
        "fetched_at": time.time(),
    })


@app.post("/api/trade")
def api_trade():
    """Places a PAPER position at the current ask. Prices are re-read from
    Polymarket here rather than trusted from the page, so a stale board can't
    fill at a price that's gone."""
    body = request.get_json(silent=True) or {}
    event_id = str(body.get("event_id") or "").strip()
    market_id = str(body.get("market_id") or "").strip()
    try:
        outcome_index = int(body.get("outcome"))
    except (TypeError, ValueError):
        return jsonify({"error": "outcome (index) is required"}), 400
    if not event_id or not market_id:
        return jsonify({"error": "event_id and market_id are required"}), 400

    try:
        ctx = _game_context(event_id, fresh=True)
        poly_teams, raws = _raw_markets(ctx, fresh=True)
    except Exception as e:
        return jsonify({"error": f"Couldn't refresh prices before trading: {e}"}), 502

    raw = next((r for r in raws if r["market_id"] == market_id), None)
    if raw is None:
        return jsonify({"error": "That market isn't listed for this game anymore."}), 404
    if not raw["active"] or raw["closed"]:
        return jsonify({"error": "That market is closed."}), 409
    if not 0 <= outcome_index < len(raw["outcomes"]):
        return jsonify({"error": "Unknown outcome for that market."}), 400

    with _broker_lock:
        broker = PaperBroker.load()
        if broker.has_position(market_id):
            return jsonify({"error": "You already hold a position in this market."}), 409

        market = _price_market(raw, poly_teams, ctx, _live_state(ctx), broker.bankroll)
        outcome = market["outcomes"][outcome_index]
        if not 0 < outcome["ask"] < 1:
            return jsonify({"error": "No price to buy at right now."}), 409

        stake = body.get("stake")
        try:
            stake = float(stake) if stake not in (None, "") else outcome["stake"]
        except (TypeError, ValueError):
            return jsonify({"error": "Stake must be a number."}), 400
        if stake < 1.0:
            return jsonify({"error": "No suggested stake here (no edge at the current ask). "
                                     "Enter at least $1 to buy anyway."}), 400
        if stake > broker.bankroll:
            return jsonify({"error": f"Stake is more than your paper bankroll (${broker.bankroll:.2f})."}), 400

        position = broker.place_bet(
            market_id=market_id,
            question=raw["question"],
            side_team=outcome["name"],
            price=outcome["ask"],
            stake=stake,
            model_prob=outcome["model"],
            market_prob=outcome["ask"],
            extra={"outcome_index": outcome_index, "spec": outcome["spec"],
                   "home_abbr": ctx["home"]["abbr"], "away_abbr": ctx["away"]["abbr"],
                   "sports_market_type": raw["sports_market_type"], "event_slug": raw.get("event_slug"),
                   "espn_event_id": event_id, "source": "dashboard"},
        )
        broker.save()

    return jsonify({"position": _position_view(position, market), "portfolio": broker.summary()})


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
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    run(debug=True)
