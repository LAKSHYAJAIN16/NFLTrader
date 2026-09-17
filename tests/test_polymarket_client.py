import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.polymarket_client import parse_event_slug


def test_parses_slug_from_full_url():
    url = "https://polymarket.com/sports/nfl/nfl-det-buf-2026-09-18"
    assert parse_event_slug(url) == "nfl-det-buf-2026-09-18"


def test_parses_slug_from_url_with_trailing_query():
    url = "https://polymarket.com/sports/nfl/nfl-det-buf-2026-09-18?tid=123"
    assert parse_event_slug(url) == "nfl-det-buf-2026-09-18"


def test_passes_through_a_bare_slug_unchanged():
    assert parse_event_slug("nfl-det-buf-2026-09-18") == "nfl-det-buf-2026-09-18"


def test_strips_surrounding_whitespace_on_bare_slug():
    assert parse_event_slug("  nfl-det-buf-2026-09-18  ") == "nfl-det-buf-2026-09-18"
