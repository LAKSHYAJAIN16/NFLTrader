# NFLTrader

Watches an NFL game live (via a free ESPN feed, or optionally OpenCV/OCR
against a broadcast video feed) and narrates, play by play, whether the win
probability should move up or down and why - then (optionally) paper-trades
any resulting edge against Polymarket. No real funds or wallet are involved
anywhere in this project; every "bet" is a simulated position tracked
locally.

## The core loop: live game state -> insights

1. **`src/espn_feed.py`** - the default, recommended source for `main.py
   live`: polls ESPN's free public scoreboard/summary API every few seconds.
   Needs no API key and no per-broadcast calibration, and updates within
   seconds of a play. `src/cv/scoreboard_reader.py` (OpenCV + Tesseract OCR)
   is an alternate source (`--source cv`) for reading the scoreboard graphic
   directly off a video feed - useful for a source ESPN doesn't cover, or as
   a redundant cross-check - but it's slower to set up (needs a calibrated
   region-of-interest per broadcast) and isn't the default.
2. **`src/insights.py`** - `InsightEngine` takes that stream of game states
   and, for every meaningful change, explains the win-probability swing in
   plain English: which team it favors, by how many points, and why
   (touchdown, field goal, safety, turnover/punt, first down, or just the
   clock running down). It filters out noise below `INSIGHT_MIN_DELTA` so it
   doesn't spam a message every few seconds.
3. **`src/win_probability.py`** - the model behind the numbers: blends a
   pregame Elo prior (`src/elo.py`, bootstrapped from nflverse historical
   results) with score differential, time remaining, possession, and field
   position - weighted so the pregame prior matters most early and the score
   dominates as the clock runs out.

Try it right now with no video feed or network access needed:

```
python tools/demo_insights.py
```

That replays a scripted 4th-quarter sequence (a red-zone drive ending in a
pick-six) through the real `InsightEngine` and prints the same insight
narration `live` mode would.

## Live play analysis: catch-probability while the ball is in the air

`src/cv/trajectory.py` (`TrajectoryTracker`) is a separate, faster-latency
idea from the score/clock loop above: a score feed can only ever tell you a
play *already happened*. This module instead fits a trajectory to a thrown
ball's last few tracked (x, y) positions, projects where it's going to land,
and estimates catch probability from how many people are contesting that
spot - updating every frame while the ball is airborne. It's pure math with
no video/model dependency, so it's fully unit-tested
(`tests/test_trajectory.py`) independent of the detector that would feed it.

`src/cv/ball_tracker.py` is that detector: a pretrained YOLOv8 model (via
`ultralytics`) run per-frame to find the ball and people, feeding
`Detection`s into the tracker above. This piece is explicitly unproven -
a small, fast-moving football at broadcast resolution is a hard target for
a generic COCO-trained detector, and it hasn't been run against real video
in this environment.

Try the tracker's math with no video or model download needed:

```
python tools/demo_play_analysis.py
```

Simulates an uncontested catch and a contested one (a defender closing in)
and prints catch probability frame by frame as each scripted throw arcs in.

### Roboflow detector (recommended over the COCO fallback)

`src/cv/ball_tracker.py`'s generic COCO YOLO wasn't trained on American
football specifically - its "sports ball" class comes from photos of mostly
stationary balls across many sports, so recall on a small fast-moving NFL
football in broadcast motion blur is poor. [Roboflow Universe hosts models
fine-tuned specifically on American football footage](https://universe.roboflow.com/search?q=class%3Afootball) -
e.g. Roboflow's own blog demonstrates [RF-DETR + ByteTrack fine-tuned on an
NFL player dataset](https://blog.roboflow.com/american-football-player-tracker/)
(74.8% mAP@50, 90.8% precision), and Universe separately lists ball-specific
and player-specific American football detection models. `src/cv/roboflow_tracker.py`
is a drop-in alternative to `ball_tracker.py` (same `.detect(frame, frame_idx)`
interface, both driven by the shared `src/cv/play_watcher.py` loop) that
calls a Roboflow-hosted model instead of running YOLO locally:

```
pip install inference-sdk
export ROBOFLOW_API_KEY=<free key from roboflow.com>
export ROBOFLOW_BALL_MODEL_ID=<project-slug>/<version>      # from a Universe model's page
export ROBOFLOW_PLAYER_MODEL_ID=<project-slug>/<version>    # optional, ball-only also works
```

Pick the actual model id yourself from a Universe listing that matches your
footage (American football, not soccer - several similarly-named Universe
projects are soccer) and sanity-check its sample predictions before trusting
it; this project can't verify class names or detection quality against a
real broadcast in this environment, same caveat as the COCO path.

## Optional: news/injury signal

`src/news_signal.py` watches a fixed list of trusted NFL insider accounts
(Adam Schefter, Tom Pelissero, etc.) on X for injury/inactive news - a kind
of edge no score feed or CV pipeline can see, since it's information from
off the field. It needs a paid `X_BEARER_TOKEN`; without one it no-ops
(`is_configured()` returns `False`) rather than erroring.

## Optional: paper-trading Polymarket off those insights

`src/polymarket_client.py` reads live NFL moneyline markets from Polymarket's
public Gamma API (no auth needed - it's read-only). `src/strategy.py` compares
the model's win probability against Polymarket's price and, if they diverge
by more than `EDGE_THRESHOLD`, sizes a fractional-Kelly paper bet
(`src/paper_broker.py` tracks a simulated bankroll/positions/P&L; nothing is
ever sent to a real wallet).

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

The CV extras (`opencv-python`, `pytesseract`, `ultralytics`) are only
needed for `--source cv` and the ball-tracking/play-analysis path - they're
listed in `requirements.txt` but you can skip installing them if you're
sticking to the default ESPN feed and pregame/status/settle modes.

For CV mode you also need the Tesseract OCR binary on your PATH:
- Windows: https://github.com/UB-Mannheim/tesseract/wiki
- macOS: `brew install tesseract`
- Linux: `apt install tesseract-ocr`

`--source cv` needs a calibrated scoreboard region-of-interest for your
video source, since the graphic's on-screen position and layout differ by
broadcast:

```
python tools/save_sample_frame.py <video_path_or_url> --time 30 --out frame.png
# open frame.png, measure pixel boxes for score/clock/quarter/down&distance/field position, then:
cp data/roi.json.example data/roi.json
# edit data/roi.json with your measured [x, y, width, height] boxes
```

`down_distance`, `field_position`, and the two `possession_*_marker` boxes
are optional - without them the engine still catches scores and clock-driven
swings, it just can't call out first downs, field position, or possession
changes. Field-position OCR expects text like "OWN 35" / "OPP 22"; broadcasts
that render it differently (e.g. a team abbreviation) will need
`ScoreboardReader._parse_yard_line` adjusted, since this is inherently the
most broadcast-specific part of the pipeline and hasn't been tested against
a real feed here.

## Tech stack

- **Language**: Python, stdlib `argparse` CLI (`main.py`) - a script/CLI
  tool, not a web service.
- **Data/HTTP**: `requests` against ESPN's public scoreboard API, Polymarket's
  Gamma/CLOB APIs, and (optionally) X's recent-search API; `nflverse`'s
  historical games CSV bootstraps the Elo model.
- **CV (optional)**: `opencv-python` + `pytesseract` (Tesseract OCR) for
  scoreboard reading; `ultralytics` (YOLOv8) for ball/person detection.
- **Persistence**: flat JSON/CSV under `state/` (Elo ratings, paper
  portfolio, trade log) - no database.
- **Tests**: `pytest`, covering Elo, ESPN feed parsing, insights, strategy,
  win probability, and the trajectory tracker's pure math.

## Architecture

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

State (`state/elo_ratings.json`, `state/portfolio.json`, `state/trade_log.csv`)
persists between runs and is gitignored.

## Tests

```
pytest
```

Tests are pure/offline - no network calls, no API keys, no real video or
model downloads required.

## Going live (not implemented)

This intentionally stops short of real order placement. To extend it:
Polymarket's `py-clob-client` package handles auth (a Polygon wallet private
key) and order signing/submission against the CLOB. You'd swap
`PaperBroker.place_bet` for a real `place_order` call, and you'd want a lot
more testing first - both a backtest of the Elo edge against historical
closing lines, and real-world validation of the ball-tracking/OCR pipelines
against actual broadcast footage (everything here has been tested against
live Polymarket/ESPN data and scripted sequences, but not against a real
broadcast video feed).
