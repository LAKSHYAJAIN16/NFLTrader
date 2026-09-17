import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.paper_broker import PaperBroker
from src.strategy import evaluate_generic_market


class FakeModel:
    def __init__(self, probs):
        self.probs = probs  # spec -> model_prob

    def price(self, spec, home_abbr, away_abbr):
        return self.probs[tuple(spec)]


def moneyline_market(home_price=0.5, away_price=0.5):
    return {
        "market_id": "m1", "question": "Lions vs. Bills",
        "sports_market_type": "moneyline", "group_item_title": None,
        "outcomes": ["Lions", "Bills"], "prices": [away_price, home_price],
    }


def test_untradable_type_is_reported_as_not_tradable():
    market = {
        "market_id": "m2", "question": "Total Two-Point Conversions O/U 0.5",
        "sports_market_type": "two_point_conversions", "group_item_title": "O/U 0.5",
        "outcomes": ["Over", "Under"], "prices": [0.98, 0.99],
    }
    broker = PaperBroker(bankroll=1000)
    model = FakeModel({})
    position, tradable = evaluate_generic_market(market, "BUF", "DET", "Bills", "Lions", model, broker)
    assert position is None
    assert tradable is False


def test_tradable_but_no_edge_returns_none_position_still_tradable():
    market = moneyline_market(home_price=0.5, away_price=0.5)
    broker = PaperBroker(bankroll=1000)
    model = FakeModel({("win", "away", "full"): 0.5, ("win", "home", "full"): 0.5})
    position, tradable = evaluate_generic_market(market, "BUF", "DET", "Bills", "Lions", model, broker)
    assert position is None
    assert tradable is True


def test_real_edge_places_a_bet_with_spec_stashed_for_settlement():
    market = moneyline_market(home_price=0.5, away_price=0.5)
    broker = PaperBroker(bankroll=1000)
    model = FakeModel({("win", "away", "full"): 0.5, ("win", "home", "full"): 0.75})
    position, tradable = evaluate_generic_market(market, "BUF", "DET", "Bills", "Lions", model, broker)
    assert tradable is True
    assert position is not None
    assert position["side_team"] == "Bills"
    assert position["spec"] == ["win", "home", "full"]
    assert position["home_abbr"] == "BUF"
    assert broker.bankroll < 1000


def test_existing_position_is_skipped_but_still_tradable():
    market = moneyline_market()
    broker = PaperBroker(bankroll=1000)
    broker.positions["m1"] = {"status": "open"}
    model = FakeModel({("win", "away", "full"): 0.9, ("win", "home", "full"): 0.1})
    position, tradable = evaluate_generic_market(market, "BUF", "DET", "Bills", "Lions", model, broker)
    assert position is None
    assert tradable is True
