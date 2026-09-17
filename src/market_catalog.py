"""Turns any Polymarket NFL market object into a pricing spec the scoring
model knows how to evaluate - generically, from the market's own
`sportsMarketType`/`question`/`groupItemTitle`/`outcomes` fields, the same
way for every game. Nothing here is hardcoded per matchup: a new game is
just a new (home_alias, away_alias) pair fed into the same regexes and the
same family registry.

Market types not in TRADABLE_FAMILIES (player props, offensive yards,
touchdown counts, safety, longest FG, both-teams-to-score) are automatically
tracked-only - we have no calibrated distribution for them, so we log them
rather than guess. Any *new* sportsMarketType Polymarket adds later falls
into this bucket by default too, which is the point: unknown types never
silently get mis-priced.
"""

import re

# sportsMarketType -> (family, period). Built from the prefix pattern
# Polymarket uses consistently across every NFL event's markets.
TRADABLE_FAMILIES = {}
for _period, _prefix in [("full", ""), ("1H", "first_half_"), ("2H", "second_half_"),
                          ("Q1", "q1_"), ("Q2", "q2_"), ("Q3", "q3_"), ("Q4", "q4_")]:
    TRADABLE_FAMILIES[f"{_prefix}moneyline"] = ("moneyline", _period)
    TRADABLE_FAMILIES[f"{_prefix}spreads"] = ("spread", _period)
    TRADABLE_FAMILIES[f"{_prefix}totals"] = ("total", _period)
    TRADABLE_FAMILIES[f"{_prefix}team_totals"] = ("team_total", _period)
TRADABLE_FAMILIES["exact_margin"] = ("margin_bucket", "full")

_LINE_IN_PARENS_RE = re.compile(r"\(([+-]?\d+(?:\.\d+)?)\)")
_TOTAL_LINE_RE = re.compile(r"O/U\s+(\d+(?:\.\d+)?)", re.IGNORECASE)
_TEAM_TOTAL_RE = re.compile(r"^(.+?)\s+(?:\dH\s+|\dQ\s+)?(?:Team Total:\s*)?O/U\s+(\d+(?:\.\d+)?)$", re.IGNORECASE)
_MARGIN_PLUS_RE = re.compile(r"(\S+)\s+by\s+(\d+)\+$", re.IGNORECASE)
_MARGIN_RANGE_RE = re.compile(r"(\S+)\s+by\s+(\d+)-(\d+)$", re.IGNORECASE)


def is_tradable(sports_market_type):
    return sports_market_type in TRADABLE_FAMILIES


def parse_market(sports_market_type, question, group_item_title, outcomes, home_alias, away_alias):
    """Returns a list of (outcome_name, spec) pairs - one per outcome this
    market has a pricing spec for - or None if this market type/shape isn't
    one we can price. `spec` is a tuple scoring_model.price() understands.
    """
    family_period = TRADABLE_FAMILIES.get(sports_market_type)
    if not family_period or len(outcomes) != 2:
        return None
    family, period = family_period

    if family == "moneyline":
        return _parse_moneyline(outcomes, home_alias, away_alias, period)
    if family == "spread":
        return _parse_spread(question, outcomes, home_alias, away_alias, period)
    if family == "total":
        return _parse_total(group_item_title or question, outcomes, period)
    if family == "team_total":
        return _parse_team_total(group_item_title or question, outcomes, home_alias, away_alias, period)
    if family == "margin_bucket":
        return _parse_margin_bucket(group_item_title or question, outcomes, home_alias, away_alias)
    return None


def _team_side(name, home_alias, away_alias):
    if name == home_alias:
        return "home"
    if name == away_alias:
        return "away"
    return None


def _parse_moneyline(outcomes, home_alias, away_alias, period):
    sides = [_team_side(o, home_alias, away_alias) for o in outcomes]
    if None in sides:
        return None
    return [(outcomes[i], ("win", sides[i], period)) for i in range(2)]


def _parse_spread(question, outcomes, home_alias, away_alias, period):
    m = _LINE_IN_PARENS_RE.search(question)
    if not m:
        return None
    line0 = float(m.group(1))
    side0 = _team_side(outcomes[0], home_alias, away_alias)
    side1 = _team_side(outcomes[1], home_alias, away_alias)
    if side0 is None or side1 is None:
        return None
    return [(outcomes[0], ("cover", side0, line0, period)),
            (outcomes[1], ("cover", side1, -line0, period))]


def _parse_total(text, outcomes, period):
    m = _TOTAL_LINE_RE.search(text)
    if not m or set(o.lower() for o in outcomes) != {"over", "under"}:
        return None
    line = float(m.group(1))
    specs = []
    for o in outcomes:
        kind = "total_over" if o.lower() == "over" else "total_under"
        specs.append((o, (kind, line, period)))
    return specs


def _parse_team_total(text, outcomes, home_alias, away_alias, period):
    m = _TEAM_TOTAL_RE.search(text)
    if not m or set(o.lower() for o in outcomes) != {"over", "under"}:
        return None
    side = _team_side(m.group(1).strip(), home_alias, away_alias)
    if side is None:
        return None
    line = float(m.group(2))
    specs = []
    for o in outcomes:
        kind = "team_total_over" if o.lower() == "over" else "team_total_under"
        specs.append((o, (kind, side, line, period)))
    return specs


def _parse_margin_bucket(text, outcomes, home_alias, away_alias):
    if set(o.lower() for o in outcomes) != {"yes", "no"}:
        return None

    text = text.strip()
    if text.lower().endswith("tie"):
        side, low, high = "home", 0, 0
    else:
        # groupItemTitle/question carry a leading "Exact Margin: " label
        # inconsistently, so search rather than anchor-match at the start
        m = _MARGIN_RANGE_RE.search(text)
        if m:
            side = _team_side(m.group(1).strip(), home_alias, away_alias)
            low, high = int(m.group(2)), int(m.group(3))
        else:
            m = _MARGIN_PLUS_RE.search(text)
            if not m:
                return None
            side = _team_side(m.group(1).strip(), home_alias, away_alias)
            low, high = int(m.group(2)), None
        if side is None:
            return None

    specs = []
    for o in outcomes:
        kind = "margin_bucket" if o.lower() == "yes" else "margin_bucket_no"
        specs.append((o, (kind, side, low, high)))
    return specs
