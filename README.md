# NFLTrader

A **paper-trading** bot that finds mispriced Polymarket NFL moneyline markets
and simulates trading them. No real funds or wallet are involved - it's a
research/signal-testing harness, not a live execution system.

## How it decides a market is mispriced

1. **Pregame edge** - a 538-style Elo rating system (`src/elo.py`), bootstrapped
   from historical results (`src/data_loader.py`, via nflverse's public game
   data), produces a win probability for each team. That's compared against
   Polymarket's current price; if they diverge by more than `EDGE_THRESHOLD`
   (default 5 points), the bot paper-trades the mispriced side.
2. **Live edge (optional, CV-driven)** - `nfltrader live` points a computer-vision
   scoreboard reader (`src/cv/scoreboard_reader.py`, OpenCV + Tesseract OCR) at
   a broadcast video feed to extract score/quarter/clock in real time. That
   game state is blended with the pregame Elo prior (`src/win_probability.py`)
   into a live win probability, which is compared against Polymarket's live
   price the same way, to catch the market reacting slower than the scoreboard.

Position sizing uses fractional Kelly (`src/strategy.py`), capped at
`MAX_STAKE_PCT` of the paper bankroll per bet.

## Setup

```
pip install -r requirements.txt
```

For live/CV mode you also need the Tesseract OCR binary on your PATH:
- Windows: https://github.com/UB-Mannheim/tesseract/wiki
- macOS: `brew install tesseract`
- Linux: `apt install tesseract-ocr`

## Usage

```
python main.py pregame          # scan open NFL markets, paper-trade any Elo edge
python main.py status           # show bankroll, open positions, realized P&L
python main.py settle           # settle open bets against completed games, update Elo
python main.py live --video <path_or_stream_url> --market <condition_id>
```

Live mode needs a calibrated scoreboard region-of-interest for your video
source, since the graphic's on-screen position differs by broadcast:

```
python tools/save_sample_frame.py <video_path_or_url> --time 30 --out frame.png
# open frame.png, measure pixel boxes for the score/clock/quarter, then:
cp data/roi.json.example data/roi.json
# edit data/roi.json with your measured [x, y, width, height] boxes
```

## Architecture

```
config.py                    thresholds, paths, team-name -> abbreviation map
src/elo.py                   Elo ratings: update, win probability, persistence
src/data_loader.py           historical results -> bootstraps Elo
src/polymarket_client.py     Gamma/CLOB API reads (no auth needed, read-only)
src/win_probability.py       blends pregame Elo prior with live CV game state
src/cv/game_state.py         GameState dataclass + sanity checks
src/cv/scoreboard_reader.py  OpenCV/Tesseract scoreboard OCR
src/paper_broker.py          simulated bankroll, positions, trade log, P&L
src/strategy.py              edge detection + Kelly position sizing
main.py                      CLI: pregame / live / settle / status
```

State (`state/elo_ratings.json`, `state/portfolio.json`, `state/trade_log.csv`)
persists between runs and is gitignored.

## Going live (not implemented)

This intentionally stops short of real order placement. To extend it:
polymarket's `py-clob-client` package handles auth (a Polygon wallet private
key) and order signing/submission against the CLOB. You'd swap
`PaperBroker.place_bet` for a real `place_order` call, and you'd want a lot
more testing of the edge model first - a backtest against historical closing
lines, not just the unit tests here, before risking real USDC.
