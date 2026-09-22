"""Free, no-key live NFL game state from ESPN's public scoreboard/summary API.

This is the recommended primary source for `main.py live`: it updates within
a few seconds of a play ending, needs no per-broadcast ROI calibration, and
has none of Tesseract's OCR error. The CV scoreboard reader
(src/cv/scoreboard_reader.py) still exists for any video source ESPN doesn't
cover (or as a redundant cross-check against this feed) - it's just no
longer the fastest or most reliable path, so it isn't the default.

The exact shape of `situation.yardLine` hasn't been confirmed against a live
game in this environment (nothing was in progress when this was written) -
treat field position from this source as best-effort until validated against
a real live game, same caveat as the CV reader's field-position OCR.
"""

import time

import requests

from src.cv.game_state import GameState

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"

_STATE_FIELDS = ("home_score", "away_score", "quarter", "clock_seconds",
                  "possession_home", "down", "distance", "yard_line")


def find_event_id(home_abbr, away_abbr):
    """Looks up this week's ESPN event id for a given matchup, or None."""
    resp = requests.get(SCOREBOARD_URL, timeout=15)
    resp.raise_for_status()
    for event in resp.json().get("events", []):
        comp = event["competitions"][0]
        abbrs = {c["team"]["abbreviation"] for c in comp["competitors"]}
        if {home_abbr, away_abbr} <= abbrs:
            return event["id"]
    return None


def list_games():
    """Returns every game on ESPN's current scoreboard as a plain dict, for
    UI pickers (the web dashboard's game selector) - not used by the CLI
    itself, which already knows its matchup from --home/--away."""
    resp = requests.get(SCOREBOARD_URL, timeout=15)
    resp.raise_for_status()
    games = []
    for event in resp.json().get("events", []):
        comp = event["competitions"][0]
        by_side = {c["homeAway"]: c for c in comp["competitors"]}
        home, away = by_side.get("home"), by_side.get("away")
        if not home or not away:
            continue
        status_type = event.get("status", {}).get("type", {})
        games.append({
            "event_id": event["id"],
            "home_abbr": home["team"]["abbreviation"],
            "away_abbr": away["team"]["abbreviation"],
            "home_name": home["team"].get("shortDisplayName", home["team"]["abbreviation"]),
            "away_name": away["team"].get("shortDisplayName", away["team"]["abbreviation"]),
            "home_score": int(home.get("score", 0) or 0),
            "away_score": int(away.get("score", 0) or 0),
            "status": status_type.get("shortDetail", ""),
            "in_progress": status_type.get("state") == "in",
        })
    return games


def _parse_clock(clock_text):
    if not clock_text or ":" not in clock_text:
        return 0
    minutes, seconds = clock_text.split(":")
    return int(minutes) * 60 + int(seconds)


def _state_from_summary(data, home_abbr, away_abbr, timestamp=None):
    comp = data["header"]["competitions"][0]
    scores = {c["team"]["abbreviation"]: int(c.get("score", 0)) for c in comp["competitors"]}

    status = comp["status"]
    situation = comp.get("situation", {})

    possession_home = None
    possession_team_id = situation.get("possession")
    if possession_team_id:
        home_team_id = next(c["team"]["id"] for c in comp["competitors"] if c["homeAway"] == "home")
        possession_home = (str(possession_team_id) == str(home_team_id))

    down = situation.get("down")
    if down is not None and not (1 <= down <= 4):
        down = None

    quarter = status.get("period", 1) or 1
    clock_seconds = _parse_clock(status.get("displayClock"))
    status_type = status.get("type", {})
    if status_type.get("completed"):
        # ESPN drops period/displayClock once a game is final, which would otherwise
        # fall back to Q1 and make the model think the whole game is still left.
        quarter = 5 if "OT" in status_type.get("detail", "") else max(quarter, 4)
        clock_seconds = 0

    return GameState(
        home_score=scores.get(home_abbr, 0),
        away_score=scores.get(away_abbr, 0),
        quarter=quarter,
        clock_seconds=clock_seconds,
        possession_home=possession_home,
        down=down,
        distance=situation.get("distance"),
        yard_line=situation.get("yardLine"),
        timestamp=timestamp if timestamp is not None else time.time(),
    )


def read_game_state(event_id, home_abbr, away_abbr) -> GameState:
    resp = requests.get(SUMMARY_URL, params={"event": event_id}, timeout=15)
    resp.raise_for_status()
    return _state_from_summary(resp.json(), home_abbr, away_abbr)


def _changed(a, b):
    return any(getattr(a, f) != getattr(b, f) for f in _STATE_FIELDS)


def watch(event_id, home_abbr, away_abbr, poll_interval_sec=5.0):
    """Generator yielding a GameState each time it changes from the previous
    poll (deduped so callers don't re-process an unchanged score/down/clock
    every single poll)."""
    prev = None
    while True:
        state = read_game_state(event_id, home_abbr, away_abbr)
        if prev is None or _changed(prev, state):
            yield state
            prev = state
        time.sleep(poll_interval_sec)
