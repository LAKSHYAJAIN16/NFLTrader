# NFLTrader

> Real-time NFL win-probability feed, checked against what Polymarket thinks -- no real money, ever.

I wanted to see if I could turn live NFL games into a real-time win-probability feed and check whether it ever disagrees with Polymarket's price. It watches a game live (free ESPN feed by default, or OpenCV/OCR reading a broadcast scoreboard), narrates why win probability is swinging, and optionally paper-trades any edge against Polymarket. Every "bet" is a simulated position tracked locally -- no wallet, no real money touches this anywhere.

## How it works
- `src/espn_feed.py` polls ESPN's free scoreboard API every few seconds (default source, no key needed)
- `src/cv/scoreboard_reader.py` reads a scoreboard off video via OpenCV/Tesseract instead (`--source cv`), needs a calibrated region-of-interest per broadcast
- `src/win_probability.py` blends a pregame Elo prior (`src/elo.py`, bootstrapped from nflverse history) with score, clock, possession, and field position
- `src/insights.py` turns win-probability swings into plain-English narration (touchdown, turnover, etc.), filtered by `INSIGHT_MIN_DELTA` so it's not spamming
- `src/cv/trajectory.py` fits a thrown ball's arc to project landing spot + catch probability, fed by one of three interchangeable detectors: `src/cv/ball_tracker.py` (generic YOLOv8, no setup, unproven on real broadcast video), `src/cv/roboflow_tracker.py` (football-specific model, needs a Roboflow key), or `src/cv/huggingface_tracker.py` (local zero-shot Grounding DINO, no API key but a heavy `transformers`+`torch` install)
- `src/news_signal.py` optionally watches trusted NFL insiders on X for injury/inactive news (needs `X_BEARER_TOKEN`, no-ops without one)
- `src/polymarket_client.py` + `src/strategy.py` + `src/paper_broker.py` read Polymarket odds, size a fractional-Kelly bet against any edge, and track a simulated bankroll
- `src/scoring_model.py` fits a margin/total point distribution from Elo, calibrated against real nflverse history -- prices spreads, totals, team totals, and exact-margin buckets, not just the moneyline
- `src/market_catalog.py` turns any market's own type/text into a pricing spec generically (no per-game hardcoding); anything without a calibrated model (player props, offensive yards, TD counts, safety, 2pt conversions) is tracked, never traded

Try the insight and trajectory logic with zero network or video:
```
python tools/demo_insights.py
python tools/demo_play_analysis.py
```

## Setup
```
pip install -r requirements.txt
```
CV extras (`opencv-python`, `pytesseract`, `ultralytics`) are only needed for `--source cv` and ball-tracking -- skip them if you're sticking to ESPN and pregame/status/settle. For CV mode you also need the Tesseract OCR binary on your PATH ([Windows](https://github.com/UB-Mannheim/tesseract/wiki), `brew install tesseract`, `apt install tesseract-ocr`), plus a calibrated scoreboard ROI since layout differs by broadcast:
```
python tools/save_sample_frame.py <video_path_or_url> --time 30 --out frame.png
cp data/roi.json.example data/roi.json   # edit with your measured [x, y, width, height] boxes
```
For the Roboflow detector instead of the COCO fallback:
```
pip install inference-sdk
export ROBOFLOW_API_KEY=<free key from roboflow.com>
export ROBOFLOW_BALL_MODEL_ID=<project-slug>/<version>
```
For the local Hugging Face detector (`--detector huggingface`) -- no account or API key needed at
all, unlike the other two, but a heavy install and download:
```
pip install transformers torch
```
(Correction on something claimed earlier in this project: Hugging Face's *hosted* inference API was
assumed to allow free anonymous access. Tested directly -- it now 401s without a token, same as
Roboflow. Running the model locally is the actual zero-credential option.)

## Running it
```
python main.py pregame                     # scan the coming week's moneylines, paper-trade any Elo edge
python main.py trade-game <polymarket_game_url_or_slug>   # EVERY market for one game -- spreads, totals,
                                            # team totals, exact margin, all half/quarter breakdowns too
python main.py status                      # bankroll, open positions, realized P&L
python main.py settle                      # settle bets against completed games, update Elo

python main.py live --home KC --away SF
python main.py live --market <polymarket_condition_id>                       # teams inferred from the market
python main.py live --source cv --video <path_or_url> --home KC --away SF    # CV/OCR instead of ESPN
```

`trade-game` takes a full `https://polymarket.com/sports/nfl/nfl-det-buf-2026-09-18` URL or the bare
slug. It logs *every* market it finds to `state/market_catalog.csv` (tradable or not, deduped across
runs) and skips trading (but still logs) anything under `MIN_MARKET_VOLUME` ($500 by default) -- a
$0-volume quote is a seeded default price, not a real market consensus, so there's no real edge to
find against one. Individual player-prop markets (e.g. "Josh Allen 2+ Touchdowns") aren't in this list:
they're rendered straight into Polymarket's page HTML rather than served from the public API, so
they're not reachable without scraping something undocumented -- not done here.

## Layout
```
src/elo.py                   Elo ratings + win probability
src/espn_feed.py             live game state from ESPN (default live source)
src/win_probability.py       blends Elo prior with live game state
src/insights.py              GameState stream -> plain-English WP narration
src/cv/                      scoreboard OCR, ball tracking, trajectory projection
src/news_signal.py           off-field injury/news signal from trusted X accounts
src/polymarket_client.py     Polymarket Gamma/CLOB reads (read-only, no auth)
src/scoring_model.py         calibrated margin/total distribution -- prices every market family
src/market_catalog.py        generic market-type -> pricing-spec registry and text parsers
src/market_log.py            appends every discovered market to state/market_catalog.csv
src/strategy.py              edge detection + Kelly position sizing
src/paper_broker.py          simulated bankroll, positions, trade log, P&L
main.py                      CLI: pregame / trade-game / live / watch-play / settle / status
```
State (Elo ratings, portfolio, trade log, market catalog) lives in gitignored flat JSON/CSV under
`state/` -- no database.

## Tests
```
pytest
```
All offline -- no network calls, no API keys, no real video or model downloads.

## A real limitation: half/quarter settlement

`settle` can resolve any full-game position (moneyline, spread, total, team total, exact margin) from
a final score. It can't resolve half/quarter positions the same way -- that needs real quarter-by-quarter
scoring data, which nflverse's basic results file doesn't carry. Those positions are correctly left open
rather than guessed at; adding a play-by-play data source would close this gap.

## Not here: placing real bets
This stops short of real order placement on purpose. Polymarket's `py-clob-client` handles wallet auth and order signing if I ever wanted to extend it, but I'd want to backtest the Elo edge against historical closing lines and validate the CV/OCR pipeline against real broadcast footage first.
