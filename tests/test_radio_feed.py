import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.radio_feed import extract_events


def test_detects_touchdown():
    assert extract_events("and that's a touchdown for the Bills!") == ["touchdown"]


def test_detects_interception():
    assert extract_events("intercepted by the defense") == ["interception"]


def test_detects_multiple_events_in_one_chunk():
    events = extract_events("he fumbles the ball and it's recovered, but wait, a penalty on the play")
    assert set(events) == {"fumble", "penalty"}


def test_no_events_in_ordinary_commentary():
    assert extract_events("second and seven from the thirty five yard line") == []


def test_case_insensitive():
    assert extract_events("TOUCHDOWN!!!") == ["touchdown"]


def test_field_goal_phrase_match():
    assert extract_events("the kick is up... it's good, field goal") == ["field_goal"]


def test_injury_variants():
    assert extract_events("he looks hurt on that play") == ["injury"]
    assert extract_events("carted off the field") == ["injury"]
