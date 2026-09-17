import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src import strategy
from src.paper_broker import PaperBroker


def test_no_stake_when_no_edge():
    assert strategy.kelly_stake(model_prob=0.5, price=0.5, bankroll=1000) == 0.0


def test_stake_capped_at_max_pct():
    stake = strategy.kelly_stake(model_prob=0.9, price=0.3, bankroll=1000)
    assert stake <= config.MAX_STAKE_PCT * 1000 + 1e-6


def test_evaluate_market_skips_small_edge():
    broker = PaperBroker(bankroll=1000)
    market = {
        "market_id": "abc", "question": "Chiefs vs 49ers",
        "home_abbr": "KC", "away_abbr": "SF",
        "home_price": 0.55, "away_price": 0.45,
    }
    position = strategy.evaluate_market(market, model_home_prob=0.56, broker=broker)
    assert position is None


def test_evaluate_market_trades_on_real_edge():
    broker = PaperBroker(bankroll=1000)
    market = {
        "market_id": "abc", "question": "Chiefs vs 49ers",
        "home_abbr": "KC", "away_abbr": "SF",
        "home_price": 0.50, "away_price": 0.50,
    }
    position = strategy.evaluate_market(market, model_home_prob=0.70, broker=broker)
    assert position is not None
    assert position["side_team"] == "KC"
    assert broker.bankroll < 1000
