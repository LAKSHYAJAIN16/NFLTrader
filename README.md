# NFLTrader

> Real-time NFL win-probability feed, checked against what Polymarket thinks -- no real money, ever.

I wanted to see if I could turn live NFL games into a real-time win-probability feed and check whether it ever disagrees with Polymarket's price. It watches a game live (free ESPN feed by default, or OpenCV/OCR reading a broadcast scoreboard), narrates why win probability is swinging, and optionally paper-trades any edge against Polymarket. Every "bet" is a simulated position tracked locally -- no wallet, no real money touches this anywhere.

## How it works
- `src/espn_feed.py` polls ESPN's free scoreboard API every few seconds (default source, no key needed)
- `src/cv/scoreboard_reader.py` reads a scoreboard off video via OpenCV/Tesseract instead (`--source cv`), needs a calibrated region-of-interest per broadcast
- `src/win_probability.py` blends a pregame Elo prior (`src/elo.py`, bootstrapped from nflverse history) with score, clock, possession, and field position
- `src/insights.py` turns win-probability swings into plain-English narration (touchdown, turnover, etc.), filtered by `INSIGHT_MIN_DELTA` so it's not spamming
- `src/cv/trajectory.py` fits a thrown ball's arc to project landing spot + catch probability, fed by `src/cv/ball_tracker.py` (generic YOLOv8, unproven on real broadcast video) or `src/cv/roboflow_tracker.py` (football-specific model, needs a Roboflow key)
- `src/news_signal.py` optionally watches trusted NFL insiders on X for injury/inactive news (needs `X_BEARER_TOKEN`, no-ops without one)
- `src/polymarket_client.py` + `src/strategy.py` + `src/paper_broker.py` read Polymarket odds, size a fractional-Kelly bet against any edge, and track a simulated bankroll

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

## Running it
```
python main.py pregame                     # scan the coming week's markets, paper-trade any Elo edge
python main.py status                      # bankroll, open positions, realized P&L
python main.py settle                      # settle bets against completed games, update Elo

python main.py live --home KC --away SF
python main.py live --market <polymarket_condition_id>                       # teams inferred from the market
python main.py live --source cv --video <path_or_url> --home KC --away SF    # CV/OCR instead of ESPN
```

## Layout
```
src/elo.py                   Elo ratings + win probability
src/espn_feed.py             live game state from ESPN (default live source)
src/win_probability.py       blends Elo prior with live game state
src/insights.py              GameState stream -> plain-English WP narration
src/cv/                      scoreboard OCR, ball tracking, trajectory projection
src/news_signal.py           off-field injury/news signal from trusted X accounts
src/polymarket_client.py     Polymarket Gamma/CLOB reads (read-only, no auth)
src/strategy.py              edge detection + Kelly position sizing
src/paper_broker.py          simulated bankroll, positions, trade log, P&L
main.py                      CLI: pregame / live / watch-play / settle / status
```
State (Elo ratings, portfolio, trade log) lives in gitignored flat JSON/CSV under `state/` -- no database.

## Tests
```
pytest
```
All offline -- no network calls, no API keys, no real video or model downloads.

## Not here: placing real bets
This stops short of real order placement on purpose. Polymarket's `py-clob-client` handles wallet auth and order signing if I ever wanted to extend it, but I'd want to backtest the Elo edge against historical closing lines and validate the CV/OCR pipeline against real broadcast footage first.
