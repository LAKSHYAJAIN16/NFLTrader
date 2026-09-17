"""NFLTrader CLI - watches NFL games live and narrates win-probability and
play-level insights; optionally paper-trades any edge against Polymarket.

Modes:
  pregame    Fetch live NFL markets, compare Elo win probs to market prices,
             paper-trade any edge found.
  live       Narrate win-probability insights play by play from a live game
             state source (--source espn, the default, or cv for OCR off a
             video feed). If --market is given, also compares against
             Polymarket's live price and paper-trades any edge.
  watch-play Narrate ball-in-air catch probability, frame by frame, off a
             video feed (needs a real-time object detector - see README).
  settle     Check cached results for completed games and settle open bets,
             updating Elo ratings from the final scores.
  status     Print the paper portfolio's current bankroll, positions, P&L.
"""

import argparse
import time
from datetime import datetime, timedelta, timezone

import config
from src import data_loader, espn_feed, insights, polymarket_client, strategy, win_probability
from src.elo import EloRatings
from src.paper_broker import PaperBroker


def _parse_game_start(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace(" ", "T").replace("+00", "+00:00"))
    except ValueError:
        return None


def _within_lookahead(market, days=config.MARKET_LOOKAHEAD_DAYS):
    start = _parse_game_start(market.get("game_start"))
    if start is None:
        return True  # can't tell, don't silently skip it
    now = datetime.now(timezone.utc)
    return now <= start <= now + timedelta(days=days)


def cmd_pregame(args):
    elo = EloRatings.load()
    if not elo.ratings:
        n = data_loader.bootstrap_elo(elo)
        print(f"Bootstrapped Elo from {n} historical games.")
        elo.save()

    broker = PaperBroker.load()
    all_markets = polymarket_client.get_nfl_markets()
    markets = [m for m in all_markets if _within_lookahead(m)]
    print(f"Found {len(all_markets)} open NFL markets, {len(markets)} within "
          f"the next {config.MARKET_LOOKAHEAD_DAYS} days.")

    trades = 0
    for m in markets:
        model_home_prob = elo.expected_home_win_prob(m["home_abbr"], m["away_abbr"])
        position = strategy.evaluate_market(m, model_home_prob, broker)
        if position:
            trades += 1
            print(f"  BET {position['side_team']:>4} @ {position['entry_price']:.2f} "
                  f"stake=${position['stake']:.2f}  ({m['question']})")

    broker.save()
    print(f"Placed {trades} paper trade(s). Bankroll: ${broker.bankroll:.2f}")


def _game_state_stream(args, home_abbr, away_abbr):
    """Yields GameStates from whichever source was requested. `espn` (default)
    is free, needs no calibration, and updates within seconds of a play - use
    `cv` only when you specifically need to watch a video source ESPN doesn't
    cover (see README for the tradeoffs)."""
    if args.source == "espn":
        event_id = args.event or espn_feed.find_event_id(home_abbr, away_abbr)
        if not event_id:
            raise SystemExit(f"No {away_abbr} @ {home_abbr} game found on ESPN's current "
                              f"scoreboard. Pass --event <espn_event_id> explicitly if it's "
                              f"outside the current week, or use --source cv with --video.")
        print(f"Polling ESPN event {event_id} every {args.interval:.0f}s ...")
        yield from espn_feed.watch(event_id, home_abbr, away_abbr, poll_interval_sec=args.interval)
    else:
        from src.cv.scoreboard_reader import ScoreboardReader
        if not args.video:
            raise SystemExit("--source cv requires --video <path_or_url>.")
        print(f"Reading scoreboard from {args.video} every {args.interval:.0f}s ...")
        yield from ScoreboardReader().read_video(args.video, sample_interval_sec=args.interval)


def cmd_live(args):
    elo = EloRatings.load()
    if not elo.ratings:
        data_loader.bootstrap_elo(elo)
        elo.save()

    market = None
    if args.market:
        markets = {m["market_id"]: m for m in polymarket_client.get_nfl_markets()}
        market = markets.get(args.market)
        if not market:
            raise SystemExit(f"Market id {args.market} not found among open NFL markets.")
        home_abbr, away_abbr = market["home_abbr"], market["away_abbr"]
    elif args.home and args.away:
        home_abbr, away_abbr = args.home.upper(), args.away.upper()
    else:
        raise SystemExit("Provide either --market (Polymarket condition id) or both --home/--away.")

    pregame_home_prob = elo.expected_home_win_prob(home_abbr, away_abbr)
    engine = insights.InsightEngine(pregame_home_prob, home_abbr=home_abbr, away_abbr=away_abbr)
    broker = PaperBroker.load() if market else None

    print(f"Watching {away_abbr} @ {home_abbr} (pregame model: {home_abbr} {pregame_home_prob:.0%})...")

    for state in _game_state_stream(args, home_abbr, away_abbr):
        insight = engine.process(state)
        if insight:
            print(f"  [{state.quarter}Q {state.clock_seconds // 60}:{state.clock_seconds % 60:02d}] "
                  f"{insight.message}")

        if market:
            live_price = polymarket_client.get_market_price(market["market_id"])
            market["home_price"] = live_price
            market["away_price"] = 1 - live_price
            position = strategy.evaluate_market(market, engine.win_prob, broker)
            if position:
                print(f"    -> BET {position['side_team']} @ {position['entry_price']:.2f} "
                      f"stake=${position['stake']:.2f}")
                broker.save()

    if broker:
        broker.save()


def cmd_settle(args):
    elo = EloRatings.load()
    broker = PaperBroker.load()
    games = data_loader.load_completed_games(min_season=args.season)

    by_matchup = {(g["home_team"], g["away_team"]): g for g in games}
    settled = 0
    for position in broker.open_positions():
        # market_id alone doesn't carry team info once loaded from disk in a
        # fresh process, so positions store enough (side_team + question) to
        # cross-reference; here we match on any completed game whose teams
        # appear in the question text.
        matchup = _match_position_to_game(position, by_matchup)
        if not matchup:
            continue
        winner = matchup["home_team"] if matchup["home_score"] > matchup["away_score"] else matchup["away_team"]
        if matchup["home_score"] == matchup["away_score"]:
            continue  # ties don't resolve a moneyline market; skip
        broker.settle_market(position["market_id"], winner)
        elo.update(matchup["home_team"], matchup["away_team"],
                    matchup["home_score"], matchup["away_score"])
        settled += 1

    broker.save()
    elo.save()
    print(f"Settled {settled} position(s).")
    print(broker.summary())


def _match_position_to_game(position, by_matchup):
    for (home, away), game in by_matchup.items():
        if home in position["question"] or away in position["question"] \
                or position["side_team"] in (home, away):
            return game
    return None


def cmd_status(args):
    broker = PaperBroker.load()
    s = broker.summary()
    print(f"Bankroll:        ${s['bankroll']:.2f}")
    print(f"Open positions:  {s['open_positions']}")
    print(f"Settled bets:    {s['settled_bets']}  ({s['wins']}W-{s['losses']}L)")
    print(f"Realized P&L:    ${s['realized_pnl']:.2f}  ({s['roi_pct']:+.1f}% of starting bankroll)")


def _pick_play_detector(args):
    from src.cv import roboflow_tracker

    if args.detector == "roboflow" or (args.detector == "auto" and roboflow_tracker.is_configured()):
        print("Using Roboflow detector...")
        return roboflow_tracker.RoboflowTracker()

    from src.cv.ball_tracker import BallTracker
    print("Using generic COCO YOLO detector (set ROBOFLOW_API_KEY + "
          "ROBOFLOW_*_MODEL_ID for the fine-tuned option - see README)...")
    return BallTracker()


def cmd_watch_play(args):
    from src.cv.play_watcher import watch_video
    from src.cv.trajectory import TrajectoryTracker

    try:
        detector = _pick_play_detector(args)
    except RuntimeError as e:
        raise SystemExit(str(e))
    tracker = TrajectoryTracker()

    print(f"Watching {args.video} for live catch-probability predictions...")
    for prediction in watch_video(args.video, detector, tracker,
                                   sample_every_n_frames=args.sample_every):
        print(f"  frame {prediction.frame_idx}: {prediction.message}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)

    sub.add_parser("pregame").set_defaults(func=cmd_pregame)

    p_live = sub.add_parser("live")
    p_live.add_argument("--source", choices=["espn", "cv"], default="espn",
                         help="espn (default): free live-feed polling, low latency, no calibration. "
                              "cv: OCR a broadcast video feed instead (needs --video + ROI calibration).")
    p_live.add_argument("--video", help="Video file path or stream URL (required for --source cv)")
    p_live.add_argument("--event", help="ESPN event id (optional; auto-looked-up from --home/--away otherwise)")
    p_live.add_argument("--market", help="Polymarket condition/market id (optional; enables paper-trading)")
    p_live.add_argument("--home", help="Home team abbreviation, e.g. KC (if not using --market)")
    p_live.add_argument("--away", help="Away team abbreviation, e.g. SF (if not using --market)")
    p_live.add_argument("--interval", type=float, default=5.0, help="Seconds between reads/polls")
    p_live.set_defaults(func=cmd_live)

    p_settle = sub.add_parser("settle")
    p_settle.add_argument("--season", type=int, default=None)
    p_settle.set_defaults(func=cmd_settle)

    sub.add_parser("status").set_defaults(func=cmd_status)

    p_watch = sub.add_parser("watch-play")
    p_watch.add_argument("--video", required=True, help="Video file path or stream URL")
    p_watch.add_argument("--detector", choices=["auto", "roboflow", "coco"], default="auto",
                          help="auto (default): Roboflow if ROBOFLOW_API_KEY is set, else COCO YOLO.")
    p_watch.add_argument("--sample-every", type=int, default=1,
                          help="Only run detection on every Nth frame (trade resolution for speed)")
    p_watch.set_defaults(func=cmd_watch_play)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
