# NFLTrader

Watches an NFL broadcast with computer vision and narrates, play by play,
whether the win probability should move up or down and why - then
(optionally) paper-trades any resulting edge against Polymarket. No real
funds or wallet are involved anywhere in this project.

## The core loop: CV -> insights

1. **`src/cv/scoreboard_reader.py`** - OpenCV + Tesseract OCR reads the
   on-screen scoreboard graphic off a broadcast video feed every few seconds:
   score, quarter, clock, down & distance, field position, and (if configured)
   which team has the ball.
2. **`src/insights.py`** - `InsightEngine` takes that stream of readings and,
   for every meaningful change, explains the win-probability swing in plain
   English: which team it favors, by how many points, and why (touchdown,
   field goal, safety, turnover/punt, first down, or just the clock running
   down). It filters out OCR noise below `INSIGHT_MIN_DELTA` so it doesn't
   spam a message every 5 seconds.
3. **`src/win_probability.py`** - the model behind the numbers: blends a
   pregame Elo prior (`src/elo.py`, bootstrapped from nflverse historical
   results) with score differential, time remaining, possession, and field
   position - weighted so the pregame prior matters most early and the score
   dominates as the clock runs out.

Try it right now with no video feed needed:

```
python tools/demo_insights.py
```

That replays a scripted 4th-quarter sequence (a red-zone drive ending in a
pick-six) through the real `InsightEngine` and prints the same insight
narration `live` mode would.

## Optional: paper-trading Polymarket off those insights

`src/polymarket_client.py` reads live NFL moneyline markets from Polymarket's
public Gamma API (no auth needed - it's read-only). `src/strategy.py` compares
the model's win probability against Polymarket's price and, if they diverge
by more than `EDGE_THRESHOLD`, sizes a fractional-Kelly paper bet
(`src/paper_broker.py` tracks a simulated bankroll/positions/P&L; nothing is
ever sent to a real wallet).

```
python main.py pregame          # scan the coming week's markets, paper-trade any Elo edge
python main.py status           # show bankroll, open positions, realized P&L
python main.py settle           # settle open bets against completed games, update Elo
python main.py live --video <path_or_url> --home KC --away SF          # insights only
python main.py live --video <path_or_url> --market <condition_id>      # insights + paper-trading
```

## Setup

```
pip install -r requirements.txt
```

For CV mode you also need the Tesseract OCR binary on your PATH:
- Windows: https://github.com/UB-Mannheim/tesseract/wiki
- macOS: `brew install tesseract`
- Linux: `apt install tesseract-ocr`

`live` mode needs a calibrated scoreboard region-of-interest for your video
source, since the graphic's on-screen position and layout differ by
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

## Architecture

```
config.py                    thresholds, paths, team-name -> abbreviation map
src/elo.py                   Elo ratings: update, win probability, persistence
src/data_loader.py           historical results -> bootstraps Elo
src/cv/game_state.py         GameState dataclass + sanity checks
src/cv/scoreboard_reader.py  OpenCV/Tesseract scoreboard OCR
src/win_probability.py       blends pregame Elo prior with live CV game state
src/insights.py              turns a GameState stream into plain-English WP insights
src/polymarket_client.py     Gamma/CLOB API reads (no auth needed, read-only)
src/paper_broker.py          simulated bankroll, positions, trade log, P&L
src/strategy.py              edge detection + Kelly position sizing
main.py                      CLI: pregame / live / settle / status
tools/demo_insights.py       runs InsightEngine over a scripted sequence, no video needed
tools/save_sample_frame.py   grabs a frame from a video source for ROI calibration
```

State (`state/elo_ratings.json`, `state/portfolio.json`, `state/trade_log.csv`)
persists between runs and is gitignored.

## Going live (not implemented)

This intentionally stops short of real order placement. To extend it:
Polymarket's `py-clob-client` package handles auth (a Polygon wallet private
key) and order signing/submission against the CLOB. You'd swap
`PaperBroker.place_bet` for a real `place_order` call, and you'd want a lot
more testing first - both a backtest of the Elo edge against historical
closing lines, and real-world validation of the CV reader against an actual
broadcast (everything here has been tested against live Polymarket data and
a scripted insight sequence, but not against real video).
