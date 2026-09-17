"""NFLTrader CLI - a paper-trading bot for Polymarket NFL moneyline markets.

Modes:
  pregame   Fetch live NFL markets, compare Elo win probs to market prices,
            paper-trade any edge found (default).
  live      Continuously read game state off a video feed with the CV
            scoreboard reader and paper-trade a live edge as it develops.
  settle    Check cached results for completed games and settle open bets,
            updating Elo ratings from the final scores.
  status    Print the paper portfolio's current bankroll, positions, P&L.
"""

import argparse
import time
from datetime import datetime, timedelta, timezone

import config
from src import data_loader, polymarket_client, strategy, win_probability
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


def cmd_live(args):
    from src.cv.scoreboard_reader import ScoreboardReader

    elo = EloRatings.load()
    broker = PaperBroker.load()
    markets = {m["market_id"]: m for m in polymarket_client.get_nfl_markets()}
    market = markets.get(args.market)
    if not market:
        raise SystemExit(f"Market id {args.market} not found among open NFL markets.")

    pregame_home_prob = elo.expected_home_win_prob(market["home_abbr"], market["away_abbr"])
    reader = ScoreboardReader()

    print(f"Watching {market['question']} via {args.video} ...")
    for state in reader.read_video(args.video, sample_interval_sec=args.interval):
        live_price = polymarket_client.get_market_price(market["market_id"])
        market["home_price"] = live_price
        market["away_price"] = 1 - live_price

        model_home_prob = win_probability.live_home_win_prob(
            pregame_home_prob, state.home_score, state.away_score,
            state.quarter, state.clock_seconds, state.possession_home,
        )
        print(f"  Q{state.quarter} {state.clock_seconds // 60}:{state.clock_seconds % 60:02d}  "
              f"{market['away_abbr']} {state.away_score} - {state.home_score} {market['home_abbr']}  "
              f"model_home_wp={model_home_prob:.2f} market_home_price={live_price:.2f}")

        position = strategy.evaluate_market(market, model_home_prob, broker)
        if position:
            print(f"  BET {position['side_team']} @ {position['entry_price']:.2f} "
                  f"stake=${position['stake']:.2f}")
            broker.save()

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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)

    sub.add_parser("pregame").set_defaults(func=cmd_pregame)

    p_live = sub.add_parser("live")
    p_live.add_argument("--video", required=True, help="Video file path or stream URL")
    p_live.add_argument("--market", required=True, help="Polymarket condition/market id to trade")
    p_live.add_argument("--interval", type=float, default=5.0, help="Seconds between CV reads")
    p_live.set_defaults(func=cmd_live)

    p_settle = sub.add_parser("settle")
    p_settle.add_argument("--season", type=int, default=None)
    p_settle.set_defaults(func=cmd_settle)

    sub.add_parser("status").set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
