# NFLTrader

I wanted to see if I could turn live NFL games into a real-time win-probability feed, then check whether that number ever disagrees with what Polymarket thinks. So this watches a game live (free ESPN feed by default, or optionally OpenCV/OCR reading a broadcast's scoreboard graphic directly), narrates play by play whether win probability should be swinging up or down and why, and -- if you want -- paper-trades any edge it finds against Polymarket. No real money or wallet touches this anywhere; every "bet" is a simulated position tracked locally.

## The core loop: game state to insights

1. **`src/espn_feed.py`** is the default source for `main.py live` -- it polls ESPN's free public scoreboard/summary API every few seconds. No API key, no calibration, updates within seconds of a play. `src/cv/scoreboard_reader.py` (OpenCV + Tesseract) is the alternate path (`--source cv`) for reading the scoreboard straight off a video feed -- useful for something ESPN doesn't cover, or as a cross-check -- but it needs a calibrated region-of-interest per broadcast, so it's more setup and not the default.
2. **`src/insights.py`** (`InsightEngine`) takes that stream of game states and, whenever something meaningful changes, explains the win-probability swing in plain English -- which team it favors, by how many points, and why (touchdown, field goal, safety, turnover, first down, or just the clock draining). Swings below `INSIGHT_MIN_DELTA` get filtered out so it's not spamming you every few seconds.
3. **`src/win_probability.py`** is the model behind the numbers -- it blends a pregame Elo prior (`src/elo.py`, bootstrapped off nflverse's historical results) with score differential, time remaining, possession, and field position. The prior matters most early in the game; score takes over as the clock runs out.

You can try the whole insight loop right now with zero network access or video:

```
python tools/demo_insights.py
```

That replays a scripted 4th-quarter sequence (a red-zone drive ending in a pick-six) through the real `InsightEngine` and prints the same narration `live` mode would give you.

## Catching the ball before it lands

`src/cv/trajectory.py` (`TrajectoryTracker`) is a separate idea from the score/clock stuff above -- a score feed can only tell you a play already happened. This fits a trajectory to a thrown ball's last few tracked positions, projects where it's landing, and estimates catch probability from how many people are contesting that spot, updating every frame while the ball's in the air. It's pure math, no model dependency, so it's fully unit tested (`tests/test_trajectory.py`) independent of whatever feeds it detections.

`src/cv/ball_tracker.py` is that detector -- a pretrained YOLOv8 model run per frame to find the ball and people. I'll be honest, this piece is unproven: a small fast-moving football at broadcast resolution is a hard target for a generic COCO-trained detector, and I haven't run it against real video yet.

Try the tracker's math with no video or model download needed:

```
python tools/demo_play_analysis.py
```

That simulates an uncontested catch and a contested one (defender closing in) and prints catch probability frame by frame as scripted throws arc in.

### Roboflow detector (better than the COCO fallback)

The generic COCO YOLO in `ball_tracker.py` wasn't trained on football specifically, so its "sports ball" class does poorly on a small fast ball in broadcast motion blur. Roboflow Universe hosts models fine-tuned on actual American football footage -- Roboflow's own blog has an RF-DETR + ByteTrack tracker trained on an NFL dataset (74.8% mAP@50, 90.8% precision), and there are separate ball- and player-specific models too. `src/cv/roboflow_tracker.py` is a drop-in replacement for `ball_tracker.py` (same `.detect(frame, frame_idx)` interface, both driven by the shared `src/cv/play_watcher.py` loop) that calls a Roboflow-hosted model instead of running YOLO locally:

```
pip install inference-sdk
export ROBOFLOW_API_KEY=<free key from roboflow.com>
export ROBOFLOW_BALL_MODEL_ID=<project-slug>/<version>      # from a Universe model's page
export ROBOFLOW_PLAYER_MODEL_ID=<project-slug>/<version>    # optional, ball-only also works
```

Pick the model id yourself from a Universe listing that actually matches your footage -- several similarly-named projects are soccer, not football -- and sanity-check its predictions before trusting it. Same caveat as the COCO path: I can't verify detection quality against real broadcast video in this environment.

## Optional: news/injury signal

`src/news_signal.py` watches a fixed list of trusted NFL insiders (Adam Schefter, Tom Pelissero, etc.) on X for injury/inactive news -- an edge no score feed or CV pipeline can see, since it's happening off the field. It needs a paid `X_BEARER_TOKEN`; without one it just no-ops (`is_configured()` returns `False`) instead of erroring out.

## Optional: paper-trading Polymarket off those insights

`src/polymarket_client.py` reads live NFL moneyline markets from Polymarket's public Gamma API (read-only, no auth needed). `src/strategy.py` compares my model's win probability against Polymarket's price, and if they diverge by more than `EDGE_THRESHOLD`, sizes a fractional-Kelly paper bet. `src/paper_broker.py` tracks a simulated bankroll, positions, and P&L -- nothing ever touches a real wallet.

```
python main.py pregame                     # scan the coming week's markets, paper-trade any Elo edge
python main.py status                      # show bankroll, open positions, realized P&L
python main.py settle                      # settle open bets against completed games, update Elo

# live insights, ESPN feed (default, no calibration needed)
python main.py live --home KC --away SF
python main.py live --home KC --away SF --market <polymarket_condition_id>   # + paper-trading
python main.py live --market <polymarket_condition_id>                       # teams inferred from the market

# live insights, CV/OCR off a video feed instead
python main.py live --source cv --video <path_or_url> --home KC --away SF
```

## Setup

```
pip install -r requirements.txt
```

The CV extras (`opencv-python`, `pytesseract`, `ultralytics`) are only needed for `--source cv` and the ball-tracking path -- they're in `requirements.txt` but you can skip them if you're sticking to the default ESPN feed and the pregame/status/settle commands.

For CV mode you also need the Tesseract OCR binary on your PATH:
- Windows: https://github.com/UB-Mannheim/tesseract/wiki
- macOS: `brew install tesseract`
- Linux: `apt install tesseract-ocr`

`--source cv` needs a calibrated scoreboard region-of-interest for your video source, since the graphic's position and layout differ by broadcast:

```
python tools/save_sample_frame.py <video_path_or_url> --time 30 --out frame.png
# open frame.png, measure pixel boxes for score/clock/quarter/down&distance/field position, then:
cp data/roi.json.example data/roi.json
# edit data/roi.json with your measured [x, y, width, height] boxes
```

`down_distance`, `field_position`, and the two `possession_*_marker` boxes are optional -- without them the engine still catches scores and clock-driven swings, it just can't call out first downs, field position, or possession changes. Field-position OCR expects text like "OWN 35" / "OPP 22"; if your broadcast renders it differently you'll need to tweak `ScoreboardReader._parse_yard_line`, since this is the most broadcast-specific part of the whole pipeline and I haven't tested it against a real feed.

## How it's built

- Plain Python, `argparse` CLI in `main.py` -- a script, not a web service.
- `requests` against ESPN's public scoreboard API, Polymarket's Gamma/CLOB APIs, and optionally X's search API; nflverse's historical games CSV bootstraps the Elo model.
- CV bits are optional: `opencv-python` + `pytesseract` for scoreboard OCR, `ultralytics` (YOLOv8) for ball/person detection.
- State lives in flat JSON/CSV under `state/` (Elo ratings, paper portfolio, trade log) -- no database.
- Tests run under `pytest`, covering Elo, ESPN feed parsing, insights, strategy, win probability, and the trajectory tracker's math.

Layout, if you're poking around:

```
config.py                    thresholds, paths, team-name -> abbreviation map
src/elo.py                   Elo ratings: update, win probability, persistence
src/data_loader.py           historical results -> bootstraps Elo
src/espn_feed.py             free, no-key live game state from ESPN (default live source)
src/cv/game_state.py         GameState dataclass + sanity checks
src/cv/scoreboard_reader.py  OpenCV/Tesseract scoreboard OCR (--source cv)
src/cv/ball_tracker.py       YOLOv8 ball/person detection per frame (zero-setup fallback)
src/cv/roboflow_tracker.py   Roboflow-hosted football-specific detection (recommended, needs API key)
src/cv/play_watcher.py       shared video loop driving either detector into TrajectoryTracker
src/cv/trajectory.py         projects a thrown ball's landing spot + catch probability
src/win_probability.py       blends pregame Elo prior with live game state
src/insights.py              turns a GameState stream into plain-English WP insights
src/news_signal.py           optional off-field injury/news signal from trusted X accounts
src/polymarket_client.py     Gamma/CLOB API reads (no auth needed, read-only)
src/paper_broker.py          simulated bankroll, positions, trade log, P&L
src/strategy.py              edge detection + Kelly position sizing
main.py                      CLI: pregame / live / watch-play / settle / status
tools/demo_insights.py       runs InsightEngine over a scripted sequence, no video needed
tools/demo_play_analysis.py  runs TrajectoryTracker over a scripted throw, no video/model needed
tools/save_sample_frame.py   grabs a frame from a video source for ROI calibration
```

`state/elo_ratings.json`, `state/portfolio.json`, and `state/trade_log.csv` persist between runs and are gitignored.

## Tests

```
pytest
```

All offline -- no network calls, no API keys, no real video or model downloads.

## What's not here: actually placing real bets

This intentionally stops short of real order placement. If I ever wanted to extend it, Polymarket's `py-clob-client` package handles auth (a Polygon wallet private key) and order signing against the CLOB -- you'd swap `PaperBroker.place_bet` for a real `place_order` call. I'd also want a lot more validation first: backtesting the Elo edge against historical closing lines, and testing the ball-tracking/OCR pipelines against actual broadcast footage. Everything here has been tested against live Polymarket/ESPN data and scripted sequences, but not against a real broadcast video feed.
