import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.elo import EloRatings


def test_equal_ratings_favor_home():
    elo = EloRatings()
    prob = elo.expected_home_win_prob("KC", "SF")
    assert prob > 0.5  # home-field advantage


def test_win_increases_rating():
    elo = EloRatings({"KC": 1500, "SF": 1500})
    home_before = elo.get("KC")
    elo.update("KC", "SF", home_score=27, away_score=10)
    assert elo.get("KC") > home_before
    assert elo.get("SF") < 1500


def test_bigger_margin_bigger_swing():
    elo_small = EloRatings({"KC": 1500, "SF": 1500})
    elo_small.update("KC", "SF", home_score=24, away_score=21)

    elo_big = EloRatings({"KC": 1500, "SF": 1500})
    elo_big.update("KC", "SF", home_score=45, away_score=3)

    assert (elo_big.get("KC") - 1500) > (elo_small.get("KC") - 1500)


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "elo.json"
    elo = EloRatings({"KC": 1550, "SF": 1480})
    elo.save(str(path))

    loaded = EloRatings.load(str(path))
    assert loaded.get("KC") == 1550
    assert loaded.get("SF") == 1480
