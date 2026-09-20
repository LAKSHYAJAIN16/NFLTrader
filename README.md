# NFLTrader

NFLTrader watches a game live (free ESPN feed by default, or OpenCV/OCR reading a broadcast scoreboard), turns score/clock/possession into a real-time win-probability feed blended with a pregame Elo prior, narrates why the number is swinging, and optionally paper-trades any edge it finds against Polymarket's price. Every "bet" is a simulated position tracked.

## How it works
The live feed (ESPN by default, or `--source cv` for OpenCV/Tesseract scoreboard reading off video) drives a win-probability model built on an Elo prior bootstrapped from nflverse history. Swings get turned into plain-English narration, filtered so it's not spamming. Thrown-ball trajectory projection is optional and pluggable across three detectors (YOLOv8, Roboflow, or a local zero-shot Hugging Face model), and an optional X-based news signal watches trusted NFL insiders for injury news. On the trading side, a calibrated margin/total model prices spreads, totals, team totals, and exact-margin buckets against Polymarket odds, sizes a fractional-Kelly position, and tracks a simulated bankroll. See `src/` for the module breakdown below.

Try the insight and trajectory logic with zero network or video:
```
python tools/demo_insights.py
python tools/demo_play_analysis.py
```

## Comprehensive data gathering: `watch-all`

`src/fusion.py`'s `FusionEngine` runs however many of four independent signal sources you configure -
concurrently, each in its own thread - and merges them into one event stream ordered by actual arrival,
not by source. That ordering is the point: whichever source reports something first is what you see
first, since no single source here is complete on its own.

```
python main.py watch-all --home KC --away SF                          # ESPN only
python main.py watch-all --home KC --away SF --radio-url <stream_url> # + live radio transcription
python main.py watch-all --browser-url <stream_page_url>              # + CV catch-prediction off a website
python main.py watch-all --news-team "Patrick Mahomes"                # + X injury-news polling
```

- **ESPN** (`--home`/`--away`) -- the score/clock feed, as in `live`.
- **Radio** (`--radio-url`, `src/radio_feed.py`) -- transcribes the stream locally via `faster-whisper`
  (no API key) and keyword-spots play events (touchdown, interception, fumble, sack, penalty, safety,
  injury). Verified against a real public stream: transcription came back correct, but it took 301s to
  process 10s of audio in this dev environment (~30x real-time) -- not explained by streams naturally
  being rate-limited to real-time delivery alone, so something in the network path or decode loop is a
  real bottleneck that needs diagnosing somewhere with better throughput to the stream origin. The
  transcription and event-detection logic itself is correct and unit-tested regardless.
- **CV** (`--video` or `--browser-url`, `src/cv/browser_capture.py`) -- `--browser-url` is what makes
  "point this at a stream site" work at all: `cv2.VideoCapture` can't decode a JS-rendered video player
  embedded in a page, so this launches a real headless Chromium and pulls frames via the Chrome DevTools
  Protocol's screencast instead. Verified for real, not just import-tested: loaded a page with an
  actually-playing `<video>` element and confirmed the screencast delivers real changing frames (81
  frames in 6s, measurable pixel movement) -- headless Chrome has historically had issues compositing
  video for screencast, so this was the critical thing to check before trusting it. A real streaming
  site may require a login/paywall step before the player renders (`headless=False` and log in manually
  first); some sites also detect and block headless browsers outright.
- **News** (`--news-team`, `src/news_signal.py`) -- polls X for injury news from trusted insiders.

For lower end-to-end latency at scale, the right lever is running this in a cloud VM close to the
stream/audio origin -- that network hop dominates real latency far more than local compute does, for
both the browser capture and the radio transcription paths.

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
For the local Hugging Face detector (`--detector huggingface`) -- no account or key needed, but a heavy install and download:
```
pip install transformers torch
```
Hugging Face's *hosted* inference API now 401s without a token, same as Roboflow, so running the model locally is the actual zero-credential option.

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

`trade-game` takes a full Polymarket URL or bare slug, logs every market it finds to `state/market_catalog.csv`, and skips trading (but still logs) anything under `MIN_MARKET_VOLUME` ($500 by default) since a $0-volume quote is a seeded default, not a real consensus. Player-prop markets aren't included -- they're rendered into Polymarket's page HTML rather than served from the public API.

## Web dashboard
```
python main.py web                 # http://127.0.0.1:5000, local-only by default
python main.py web --host 0.0.0.0  # also reachable from other devices on your network
```
A small Flask app (`web/app.py`) plus one static page (`web/static/index.html`, no build step, no
npm) that wraps the same modules the CLI uses -- it does not duplicate any model logic. It's operational
today as a **local dashboard only**: nothing is deployed to the internet, so the only way to "access it"
is to run the command above on a machine with this repo and hit that URL yourself (or another device on
your LAN, with `--host 0.0.0.0`). There is no public URL.

- Game picker sourced from ESPN's live scoreboard (`/api/scoreboard`)
- Live win-probability bar + sparkline and the insight-narration feed for whichever game you pick
  (`/api/game?home=..&away=..`, polled every 5s -- reuses `EloRatings`, `win_probability`, and
  `InsightEngine` exactly as `main.py live` does)
- Paper portfolio panel: bankroll, open positions, realized P&L (`/api/status`, polled every 10s,
  reads the same `state/portfolio.json` the CLI writes)

## Layout
```
src/elo.py                   Elo ratings + win probability
src/espn_feed.py             live game state from ESPN (default live source)
src/win_probability.py       blends Elo prior with live game state
src/insights.py              GameState stream -> plain-English WP narration
src/cv/                      scoreboard OCR, ball tracking, trajectory projection, browser capture
src/radio_feed.py            local live radio transcription + play-event keyword spotting
src/fusion.py                merges ESPN/radio/CV/news into one arrival-ordered event stream
src/news_signal.py           off-field injury/news signal from trusted X accounts
src/polymarket_client.py     Polymarket Gamma/CLOB reads (read-only, no auth)
src/scoring_model.py         calibrated margin/total distribution -- prices every market family
src/market_catalog.py        generic market-type -> pricing-spec registry and text parsers
src/market_log.py            appends every discovered market to state/market_catalog.csv
src/strategy.py              edge detection + Kelly position sizing
src/paper_broker.py          simulated bankroll, positions, trade log, P&L
web/app.py                   Flask API for the local dashboard (wraps the modules above, no new logic)
web/static/index.html        dashboard page: game picker, live win-prob chart, insight feed, portfolio
main.py                      CLI: pregame / trade-game / live / watch-play / watch-all / settle / status / web
```
State (Elo ratings, portfolio, trade log, market catalog) lives in gitignored flat JSON/CSV under
`state/` -- no database.

## Tests
```
pytest
```
All offline -- no network calls, no API keys, no real video or model downloads.

## Known gaps
`settle` resolves full-game positions from a final score but leaves half/quarter positions open rather than guessing -- that needs quarter-by-quarter data nflverse's basic results file doesn't carry. And real order placement is out of scope on purpose: Polymarket's `py-clob-client` handles wallet auth and signing if this ever gets extended that far, but the Elo edge needs backtesting against historical closing lines first, and the CV/OCR pipeline against real broadcast footage.
