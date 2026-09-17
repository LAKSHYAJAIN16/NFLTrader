"""Appends every market discovered for a game to state/market_catalog.csv -
the full inventory of what Polymarket lists for a game, tradable or not, so
nothing goes unrecorded just because we have no pricing model for it yet.
Deduped by market_id so re-running against the same game doesn't pile up
duplicate rows.
"""

import csv
import os
import time

import config


def _already_logged_ids(path):
    if not os.path.exists(path):
        return set()
    with open(path, newline="") as f:
        return {row["market_id"] for row in csv.DictReader(f)}


def log_markets(event_slug, home_abbr, away_abbr, raw_markets, tradable_ids):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    path = config.MARKET_CATALOG_PATH
    seen = _already_logged_ids(path)
    file_exists = os.path.exists(path)

    new_rows = [m for m in raw_markets if m["market_id"] not in seen]
    if not new_rows:
        return 0

    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["logged_at", "event_slug", "home_abbr", "away_abbr", "market_id",
                              "sports_market_type", "question", "group_item_title", "tradable"])
        for m in new_rows:
            writer.writerow([
                time.strftime("%Y-%m-%d %H:%M:%S"), event_slug, home_abbr, away_abbr,
                m["market_id"], m["sports_market_type"], m["question"], m.get("group_item_title") or "",
                m["market_id"] in tradable_ids,
            ])
    return len(new_rows)
