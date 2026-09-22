"""Read-only client for Polymarket's public Gamma and CLOB APIs.

No API key or wallet is required for market data - only order placement
(not implemented here; this project runs in paper-trading mode) needs auth.
"""

import json
import re

import requests

import config

_nfl_tag_id_cache = None
_SLUG_FROM_URL_RE = re.compile(r"polymarket\.com/sports/nfl/([a-z0-9-]+)", re.IGNORECASE)


def _get_nfl_tag_id():
    global _nfl_tag_id_cache
    if _nfl_tag_id_cache is None:
        resp = requests.get(f"{config.GAMMA_API}/tags/slug/{config.NFL_TAG_SLUG}", timeout=15)
        resp.raise_for_status()
        _nfl_tag_id_cache = resp.json()["id"]
    return _nfl_tag_id_cache


def _fetch_nfl_events(closed=False, max_pages=10):
    """Individual-game moneyline events carry a `teams` array with explicit
    home/away `ordering` - far more reliable than parsing team names out of
    a title/slug, so we page through /events rather than /markets directly.
    """
    tag_id = _get_nfl_tag_id()
    events = []
    offset = 0
    for _ in range(max_pages):
        params = {"tag_id": tag_id, "closed": str(closed).lower(), "limit": 100, "offset": offset}
        resp = requests.get(f"{config.GAMMA_API}/events", params=params, timeout=15)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        events.extend(batch)
        offset += 100
        if len(batch) < 100:
            break
    return events


def _team_abbr(team):
    name = (team.get("name") or "").strip().lower()
    if name in config.TEAM_NAME_TO_ABBR:
        return config.TEAM_NAME_TO_ABBR[name]
    raw = team.get("abbreviation")
    return raw.upper() if raw else None


def get_nfl_markets(active_only=True):
    """Return NFL moneyline markets as a list of dicts.

    Each dict: {market_id, question, home_team, away_team, home_abbr, away_abbr,
    home_price, away_price, game_start, closed}
    """
    events = _fetch_nfl_events(closed=not active_only)
    markets = []

    for event in events:
        teams = event.get("teams")
        if not teams or len(teams) != 2:
            continue
        home = next((t for t in teams if t.get("ordering") == "home"), None)
        away = next((t for t in teams if t.get("ordering") == "away"), None)
        if not home or not away:
            continue

        home_abbr = _team_abbr(home)
        away_abbr = _team_abbr(away)
        if not home_abbr or not away_abbr:
            continue

        for m in event.get("markets", []):
            if m.get("sportsMarketType") != "moneyline":
                continue  # skip spreads/totals/props sub-markets in the same event
            if active_only and (m.get("closed") or not m.get("active", True)):
                continue

            outcomes = _parse_json_field(m.get("outcomes"))
            prices = _parse_json_field(m.get("outcomePrices"))
            if not outcomes or not prices or len(outcomes) != 2:
                continue

            price_by_alias = dict(zip(outcomes, (float(p) for p in prices)))
            home_price = price_by_alias.get(home.get("alias"))
            away_price = price_by_alias.get(away.get("alias"))
            if home_price is None or away_price is None:
                continue

            markets.append({
                "market_id": m.get("conditionId") or m.get("id"),
                "question": m.get("question", ""),
                "home_team": home.get("name"),
                "away_team": away.get("name"),
                "home_abbr": home_abbr,
                "away_abbr": away_abbr,
                "home_price": home_price,
                "away_price": away_price,
                "game_start": m.get("gameStartTime") or event.get("startDate"),
                "closed": m.get("closed", False),
            })

    return markets


def parse_event_slug(slug_or_url):
    """Accepts either a bare event slug or a full polymarket.com game URL."""
    m = _SLUG_FROM_URL_RE.search(slug_or_url)
    return m.group(1) if m else slug_or_url.strip()


def get_event_markets(slug_or_url):
    """Fetches EVERY market Polymarket lists for a single game, generically -
    no filtering by market type. Returns (home_info, away_info, markets),
    where markets is a list of raw market dicts (each with 'question',
    'groupItemTitle', 'sportsMarketType', 'outcomes' (list), 'outcomePrices'
    (list of float), 'conditionId', 'closed') straight off the Gamma API,
    for src/market_catalog.py to interpret.

    This is the procedural, per-game entry point (`main.py trade-game
    <slug_or_url>`) - as opposed to get_nfl_markets(), which bulk-scans the
    whole week's moneylines for the default `pregame` command.
    """
    slug = parse_event_slug(slug_or_url)
    resp = requests.get(f"{config.GAMMA_API}/events", params={"slug": slug}, timeout=15)
    resp.raise_for_status()
    events = resp.json()
    if not events:
        raise ValueError(f"No Polymarket event found for slug '{slug}'")
    event = events[0]

    teams = event.get("teams")
    if not teams or len(teams) != 2:
        raise ValueError(f"Event '{slug}' doesn't carry the expected two-team structure")
    home = next((t for t in teams if t.get("ordering") == "home"), None)
    away = next((t for t in teams if t.get("ordering") == "away"), None)
    if not home or not away:
        raise ValueError(f"Event '{slug}' is missing home/away ordering")

    markets = _markets_from_event(event)

    home_info = {"abbr": _team_abbr(home), "alias": home.get("alias"), "name": home.get("name")}
    away_info = {"abbr": _team_abbr(away), "alias": away.get("alias"), "name": away.get("name")}
    return home_info, away_info, markets


def _markets_from_event(event):
    markets = []
    for m in event.get("markets", []):
        outcomes = _parse_json_field(m.get("outcomes"))
        prices = _parse_json_field(m.get("outcomePrices"))
        if not outcomes or not prices or len(outcomes) != len(prices):
            continue
        prices = [float(p) for p in prices]
        markets.append({
            "market_id": m.get("conditionId") or m.get("id"),
            "question": m.get("question", ""),
            "group_item_title": m.get("groupItemTitle"),
            "sports_market_type": m.get("sportsMarketType"),
            "outcomes": outcomes,
            "prices": prices,
            "asks": _outcome_asks(m, prices),
            "volume": float(m.get("volumeNum") or 0.0),
            "closed": m.get("closed", False),
            "active": m.get("active", True),
            "game_start": m.get("gameStartTime"),
            "event_slug": event.get("slug"),
        })
    return markets


def _outcome_asks(m, prices):
    """What buying each outcome actually costs right now: the first outcome's
    token trades at bestAsk, and buying the second is selling the first at
    bestBid (1 - bestBid). Falls back to the displayed price when the book
    is empty on that side."""
    if len(prices) != 2:
        return list(prices)
    best_ask, best_bid = m.get("bestAsk"), m.get("bestBid")
    first = float(best_ask) if best_ask not in (None, "") and 0 < float(best_ask) < 1 else prices[0]
    second = 1 - float(best_bid) if best_bid not in (None, "") and 0 < float(best_bid) < 1 else prices[1]
    return [round(first, 4), round(second, 4)]


def find_game_event_slugs(home_name, away_name, kickoff_iso):
    """Every Polymarket event for one game: the main game-lines event plus its
    siblings (player props, first TD scorer, highest-scoring quarter...), which
    share its slug as a prefix. Matched on team names and kickoff date, since
    event slugs use Polymarket's own abbreviations. [] if Polymarket doesn't
    list the game."""
    from datetime import datetime, timedelta

    kickoff = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
    wanted = {home_name.lower(), away_name.lower()}
    events = _fetch_nfl_events()

    def plays_on_kickoff_day(event):
        for m in event.get("markets", []):
            start = m.get("gameStartTime")
            if start:
                when = datetime.fromisoformat(start.replace(" ", "T").replace("+00", "+00:00").replace("Z", "+00:00"))
                return abs(when - kickoff) < timedelta(hours=18)
        return False

    candidates = [e for e in events
                  if {(t.get("name") or "").lower() for t in e.get("teams") or []} == wanted
                  and plays_on_kickoff_day(e)]
    if not candidates:
        return []
    main = min(candidates, key=lambda e: len(e.get("slug", "")))["slug"]
    return sorted({e["slug"] for e in events if e.get("slug", "").startswith(main)},
                  key=lambda slug: (slug != main, slug))


def get_game_markets(slugs):
    """Every market across a game's events (see find_game_event_slugs), fresh
    from the API. Returns (home_info, away_info, markets) like get_event_markets;
    each market carries its `event_slug`."""
    home_info = away_info = None
    markets = []
    for slug in slugs:
        home, away, event_markets = get_event_markets(slug)
        if home_info is None:
            home_info, away_info = home, away
        markets.extend(event_markets)
    return home_info, away_info, markets


def get_market_price(condition_id):
    """Fetch the live midpoint price for a single market from the CLOB API."""
    resp = requests.get(f"{config.CLOB_API}/midpoint", params={"token_id": condition_id}, timeout=10)
    resp.raise_for_status()
    return float(resp.json()["mid"])


def _parse_json_field(value):
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None
