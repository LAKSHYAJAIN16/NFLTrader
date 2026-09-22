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


# ESPN's abbreviations where they differ from the nflverse history the Elo
# ratings are built from.
_ELO_ABBR = {"WSH": "WAS", "LAR": "LA"}

# Clock/administrative "plays" that carry no football, shown muted in feeds.
NON_ACTION_PLAY_TYPES = {"End Period", "End of Half", "End of Game", "Timeout",
                         "Official Timeout", "Two-minute warning"}


# Typical drive start after a kickoff (touchback at the 30/35, or a return).
POST_SCORE_YARDS_TO_ENDZONE = 70


def to_elo_abbr(espn_abbr):
    return _ELO_ABBR.get(espn_abbr, espn_abbr)


def _fetch_scoreboard(params=None):
    resp = requests.get(SCOREBOARD_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _upcoming_scoreboard():
    """ESPN's default scoreboard keeps showing a finished week until the next
    one starts, so once every game on it is final, look ahead a week (and
    across the regular season / postseason boundary if that week is empty)."""
    data = _fetch_scoreboard()
    events = data.get("events", [])
    if events and any(e.get("status", {}).get("type", {}).get("state") != "post" for e in events):
        return data

    week = (data.get("week") or {}).get("number")
    season_type = (data.get("season") or {}).get("type")
    if week is None or season_type is None:
        return data
    for params in ({"week": week + 1, "seasontype": season_type},
                   {"week": 1, "seasontype": season_type + 1}):
        ahead = _fetch_scoreboard(params)
        if ahead.get("events"):
            return ahead
    return data


def list_games():
    """This week's games (or next week's once this one is fully final) as plain
    dicts for UI pickers - the web dashboard's slate. Not used by the CLI,
    which already knows its matchup from --home/--away."""
    games = []
    for event in _upcoming_scoreboard().get("events", []):
        comp = event["competitions"][0]
        by_side = {c["homeAway"]: c for c in comp["competitors"]}
        home, away = by_side.get("home"), by_side.get("away")
        if not home or not away:
            continue
        status_type = event.get("status", {}).get("type", {})
        games.append({
            "event_id": event["id"],
            "kickoff": event.get("date"),
            "home_abbr": home["team"]["abbreviation"],
            "away_abbr": away["team"]["abbreviation"],
            "home_name": home["team"].get("shortDisplayName", home["team"]["abbreviation"]),
            "away_name": away["team"].get("shortDisplayName", away["team"]["abbreviation"]),
            "home_color": home["team"].get("color"),
            "away_color": away["team"].get("color"),
            "home_score": int(home.get("score", 0) or 0),
            "away_score": int(away.get("score", 0) or 0),
            "state": status_type.get("state", "pre"),
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


def read_summary(event_id):
    resp = requests.get(SUMMARY_URL, params={"event": event_id}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def read_game_state(event_id, home_abbr, away_abbr) -> GameState:
    return _state_from_summary(read_summary(event_id), home_abbr, away_abbr)


def teams_from_summary(data):
    """{"home": {...}, "away": {...}} with abbr, name, color, score."""
    comp = data["header"]["competitions"][0]
    teams = {}
    for c in comp["competitors"]:
        team = c["team"]
        teams[c["homeAway"]] = {
            "id": str(team["id"]),
            "abbr": team["abbreviation"],
            "name": team.get("displayName", team["abbreviation"]),
            "short_name": team.get("name", team["abbreviation"]),
            "color": team.get("color"),
            "score": int(c.get("score", 0) or 0),
        }
    return teams


def plays_from_summary(data):
    """Every play so far, oldest first, flattened out of ESPN's drives.

    `offense_home` is who had the ball when the snap happened; `possession_home`
    and `yards_to_endzone` describe the field *after* the play, which is what a
    win-probability read after that play should use.
    """
    teams = teams_from_summary(data)
    home_id = teams["home"]["id"]

    drives = data.get("drives") or {}
    drive_list = list(drives.get("previous") or [])
    if drives.get("current"):
        drive_list.append(drives["current"])

    def is_home(team_ref):
        team_id = (team_ref or {}).get("id")
        return None if team_id is None else str(team_id) == home_id

    plays, seen = [], set()
    prev = {"home_score": 0, "away_score": 0, "possession_home": None, "yards_to_endzone": None}
    for drive in drive_list:
        for play in drive.get("plays") or []:
            if play.get("id") in seen:
                continue
            seen.add(play.get("id"))
            start, end = play.get("start") or {}, play.get("end") or {}
            after = end if end.get("team") else start
            play_type = (play.get("type") or {}).get("text", "")
            home_score = int(play.get("homeScore", 0) or 0)
            away_score = int(play.get("awayScore", 0) or 0)

            if play_type in NON_ACTION_PLAY_TYPES:
                # timeouts / end-of-period rows don't move the ball, but ESPN
                # stamps them with stale or goal-line end states
                possession_home, yards_to_endzone = prev["possession_home"], prev["yards_to_endzone"]
            elif play.get("scoringPlay"):
                # ESPN leaves the scorer "in possession" at the goal line; really the
                # other side is about to receive (the scorer, after a safety)
                home_scored = home_score - prev["home_score"] > away_score - prev["away_score"]
                safety = abs((home_score + away_score) - (prev["home_score"] + prev["away_score"])) == 2
                possession_home = home_scored if safety else not home_scored
                yards_to_endzone = POST_SCORE_YARDS_TO_ENDZONE
            else:
                possession_home, yards_to_endzone = is_home(after.get("team")), after.get("yardsToEndzone")

            entry = {
                "id": play.get("id"),
                "quarter": (play.get("period") or {}).get("number", 1),
                "clock_seconds": _parse_clock((play.get("clock") or {}).get("displayValue")),
                "text": (play.get("text") or "").strip(),
                "type": play_type,
                "home_score": home_score,
                "away_score": away_score,
                "scoring": bool(play.get("scoringPlay")),
                "turnover": bool(play.get("isTurnover")),
                "down_distance": start.get("downDistanceText") or None,
                "offense_home": is_home(start.get("team")),
                "possession_home": possession_home,
                "yards_to_endzone": yards_to_endzone,
            }
            plays.append(entry)
            prev = entry
    return plays


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
