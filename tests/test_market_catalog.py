import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import market_catalog as mc

HOME, AWAY = "Bills", "Lions"  # matches real observed alias text for nfl-det-buf-2026-09-18


def test_unknown_sports_market_type_is_not_tradable():
    assert mc.is_tradable("team_offensive_yards") is False
    assert mc.is_tradable("two_point_conversions") is False
    assert mc.is_tradable("player_touchdowns") is False  # hypothetical future/player-prop type


def test_all_expected_families_are_tradable():
    for t in ["moneyline", "spreads", "totals", "team_totals",
              "first_half_moneyline", "second_half_spreads", "q3_totals", "exact_margin"]:
        assert mc.is_tradable(t), t


def test_parses_full_game_moneyline():
    specs = mc.parse_market("moneyline", "Lions vs. Bills", None, ["Lions", "Bills"], HOME, AWAY)
    assert specs == [("Lions", ("win", "away", "full")), ("Bills", ("win", "home", "full"))]


def test_parses_quarter_moneyline_period():
    specs = mc.parse_market("q2_moneyline", "Lions vs. Bills: 2Q Moneyline", "2Q Moneyline",
                             ["Lions", "Bills"], HOME, AWAY)
    assert specs[0][1] == ("win", "away", "Q2")
    assert specs[1][1] == ("win", "home", "Q2")


def test_parses_spread_both_sides_from_real_shape():
    specs = mc.parse_market("spreads", "Spread: Bills (-8.5)", "Spread -8.5",
                             ["Bills", "Lions"], HOME, AWAY)
    assert specs == [("Bills", ("cover", "home", -8.5, "full")),
                      ("Lions", ("cover", "away", 8.5, "full"))]


def test_parses_first_half_spread_with_period():
    specs = mc.parse_market("first_half_spreads", "1H Spread: Lions (-3.5)", "1H Spread -3.5",
                             ["Lions", "Bills"], HOME, AWAY)
    assert specs[0][1] == ("cover", "away", -3.5, "1H")
    assert specs[1][1] == ("cover", "home", 3.5, "1H")


def test_parses_totals_from_group_item_title():
    specs = mc.parse_market("totals", "Lions vs. Bills: O/U 54.5", "O/U 54.5",
                             ["Over", "Under"], HOME, AWAY)
    assert specs == [("Over", ("total_over", 54.5, "full")), ("Under", ("total_under", 54.5, "full"))]


def test_parses_quarter_totals_period():
    specs = mc.parse_market("q1_totals", "Lions vs. Bills: 1Q O/U 10.5", "1Q O/U 10.5",
                             ["Over", "Under"], HOME, AWAY)
    assert specs[0][1] == ("total_over", 10.5, "Q1")


def test_parses_team_totals_real_shape():
    specs = mc.parse_market("team_totals", "Lions Team Total: O/U 10.5", "Lions O/U 10.5",
                             ["Over", "Under"], HOME, AWAY)
    assert specs == [("Over", ("team_total_over", "away", 10.5, "full")),
                      ("Under", ("team_total_under", "away", 10.5, "full"))]


def test_parses_first_half_team_totals():
    specs = mc.parse_market("first_half_team_totals", "Bills 1H Team Total: O/U 6.5", "Bills 1H O/U 6.5",
                             ["Over", "Under"], HOME, AWAY)
    assert specs[0][1] == ("team_total_over", "home", 6.5, "1H")


def test_parses_exact_margin_range():
    specs = mc.parse_market("exact_margin", "Exact Margin: Bills by 7-13", "Bills by 7-13",
                             ["Yes", "No"], HOME, AWAY)
    assert specs == [("Yes", ("margin_bucket", "home", 7, 13)),
                      ("No", ("margin_bucket_no", "home", 7, 13))]


def test_parses_exact_margin_open_ended():
    specs = mc.parse_market("exact_margin", "Exact Margin: Lions by 25+", "Lions by 25+",
                             ["Yes", "No"], HOME, AWAY)
    assert specs[0][1] == ("margin_bucket", "away", 25, None)


def test_parses_exact_margin_tie():
    specs = mc.parse_market("exact_margin", "Exact Margin: Tie", "Exact Margin: Tie",
                             ["Yes", "No"], HOME, AWAY)
    assert specs[0][1] == ("margin_bucket", "home", 0, 0)


def test_untradable_type_returns_none():
    assert mc.parse_market("two_point_conversions", "Total Two-Point Conversions O/U 0.5",
                            "O/U 0.5", ["Over", "Under"], HOME, AWAY) is None


def test_unparseable_shape_returns_none_gracefully():
    # e.g. spread question with no team recognized (roster typo, mismatch, etc.)
    specs = mc.parse_market("spreads", "Spread: Nobody (-8.5)", "Spread -8.5",
                             ["Nobody", "Lions"], HOME, AWAY)
    assert specs is None
