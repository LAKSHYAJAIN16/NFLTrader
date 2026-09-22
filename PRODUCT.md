# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: the builder, trading NFL games on Polymarket (paper) while watching them live, usually with the dashboard open next to the game. The job is two things at once: follow the game as it happens, and act on every Polymarket market for that game when the model and the market disagree.

Secondary: other people who clone the repo and run it themselves. They should be able to get from `git clone` to a working dashboard with the README alone, with no accounts or API keys for the core path (ESPN and Polymarket's public APIs are keyless).

## Product Purpose

NFLTrader turns a live NFL game into a win-probability feed (ESPN play-by-play blended with a pregame Elo prior), prices Polymarket's markets for that game with its own models, and paper-trades the edges it finds. The web dashboard is where that comes together for one person during a game: the slate, the live game, every market for it with model vs. market price, and the simulated portfolio.

Success: during a live game you can see what just happened, how it moved the model, which markets now disagree with the model, and place or review a paper position without leaving the page.

## Positioning

A single local tool that puts its own transparent model next to the market price for every market on a game, and explains each swing with the play that caused it. It does not relay a sportsbook's or ESPN's number as its own.

## Operating Context

- Runs locally: `python main.py web` serves the dashboard at http://127.0.0.1:5000 (`--host 0.0.0.0` for LAN).
- Data: ESPN's public scoreboard/summary API (slate, play-by-play) and Polymarket's public Gamma API (events and markets). No keys needed.
- The CLI (`pregame`, `trade-game`, `live`, `watch-all`, `settle`, `status`) shares the same modules and the same paper portfolio file (`state/portfolio.json`).
- Games are watched live on Thursdays, Sundays and Mondays; the rest of the week the page is mostly previewing the upcoming slate.

## Capabilities and Constraints

- **Paper trading only.** Every position is simulated and tracked by `PaperBroker`; there is no real-money order path anywhere in the project. Any real trading would be a new, explicit decision.
- Market types from Polymarket: moneyline, spreads, totals, team totals, and exact-margin buckets, full game and by period. `market_catalog` parses them; `scoring_model` prices spreads/totals/team totals/margins; moneyline uses the win-probability model.
- The scoring model for non-moneyline markets is pregame-only (Elo + calibrated score distributions). It does not yet update live from game state, so live "edges" on those markets can be model staleness, not real edge. The CLI refuses to trade them after kickoff without `--force`.
- Markets below `config.MIN_MARKET_VOLUME` lifetime volume are treated as illiquid (a $0-volume price is a seeded default, not a quote).
- Stakes are sized by fractional Kelly (`strategy.kelly_stake`).
- ESPN field position from the live feed is best-effort until validated against more live games.

## Evidence on Hand

- Real historical games (nflverse) bootstrap Elo; ESPN and Polymarket supply real live data. There are no testimonials, users, or performance track record; do not claim model accuracy or profitability.

## Product Principles

1. Honest numbers: show the model's own probability beside the market's, label pregame-only estimates as such, and never present simulated trades as real.
2. The play explains the swing: every change in probability or edge should trace back to something that happened in the game.
3. Every market for the game, not only the winner, with illiquid or unmodeled markets marked rather than hidden.
4. Runs anywhere with nothing to sign up for: the keyless path must keep working out of the box.
