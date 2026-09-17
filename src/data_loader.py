"""Fetches and caches historical NFL results, used to bootstrap Elo ratings."""

import csv
import os

import requests

import config


def fetch_games_csv(force=False):
    """Download nflverse's games.csv to data/games.csv, using the cache when possible."""
    if os.path.exists(config.GAMES_CSV_PATH) and not force:
        return config.GAMES_CSV_PATH

    os.makedirs(config.DATA_DIR, exist_ok=True)
    resp = requests.get(config.NFLVERSE_GAMES_URL, timeout=30)
    resp.raise_for_status()
    with open(config.GAMES_CSV_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(resp.text)
    return config.GAMES_CSV_PATH


def load_completed_games(min_season=None, max_season=None):
    """Yield completed games as dicts, sorted chronologically, from the cached CSV.

    Falls back to an empty list if no cache exists and the network fetch fails,
    so the rest of the pipeline can still run with all teams at the default rating.
    """
    try:
        path = fetch_games_csv()
    except requests.RequestException:
        if os.path.exists(config.GAMES_CSV_PATH):
            path = config.GAMES_CSV_PATH
        else:
            return []

    games = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row.get("home_score") or not row.get("away_score"):
                continue  # game hasn't been played yet
            season = int(row["season"])
            if min_season and season < min_season:
                continue
            if max_season and season > max_season:
                continue
            games.append({
                "season": season,
                "week": int(row["week"]) if row.get("week") else 0,
                "gameday": row.get("gameday", ""),
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "home_score": float(row["home_score"]),
                "away_score": float(row["away_score"]),
            })

    games.sort(key=lambda g: (g["season"], g["week"], g["gameday"]))
    return games


def bootstrap_elo(elo_ratings, min_season=None, max_season=None):
    """Replay completed games chronologically to warm up an EloRatings object."""
    games = load_completed_games(min_season=min_season, max_season=max_season)
    for g in games:
        elo_ratings.update(g["home_team"], g["away_team"], g["home_score"], g["away_score"])
    return len(games)
