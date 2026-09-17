import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src import market_log


def markets():
    return [
        {"market_id": "1", "sports_market_type": "moneyline", "question": "Lions vs. Bills",
         "group_item_title": None},
        {"market_id": "2", "sports_market_type": "two_point_conversions", "question": "2pt O/U 0.5",
         "group_item_title": "O/U 0.5"},
    ]


def test_logs_all_markets_with_tradable_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MARKET_CATALOG_PATH", str(tmp_path / "catalog.csv"))
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path))

    n = market_log.log_markets("nfl-det-buf-2026-09-18", "BUF", "DET", markets(), tradable_ids={"1"})
    assert n == 2

    with open(config.MARKET_CATALOG_PATH, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    tradable_by_id = {r["market_id"]: r["tradable"] for r in rows}
    assert tradable_by_id["1"] == "True"
    assert tradable_by_id["2"] == "False"


def test_rerun_does_not_duplicate_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MARKET_CATALOG_PATH", str(tmp_path / "catalog.csv"))
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path))

    market_log.log_markets("nfl-det-buf-2026-09-18", "BUF", "DET", markets(), tradable_ids={"1"})
    second_run_new_rows = market_log.log_markets(
        "nfl-det-buf-2026-09-18", "BUF", "DET", markets(), tradable_ids={"1"})

    assert second_run_new_rows == 0
    with open(config.MARKET_CATALOG_PATH, newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
