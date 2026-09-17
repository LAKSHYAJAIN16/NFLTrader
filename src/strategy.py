"""Turns a (model probability, market price) pair into a sized paper bet."""

import config


def kelly_stake(model_prob, price, bankroll):
    """Fractional-Kelly stake for buying a share at `price` when we believe
    the true probability of it resolving YES is `model_prob`."""
    if price <= 0 or price >= 1:
        return 0.0
    edge = model_prob - price
    if edge <= 0:
        return 0.0

    b = (1 - price) / price  # net odds received on a winning $1 stake
    full_kelly = (model_prob * (b + 1) - 1) / b
    stake_pct = max(0.0, full_kelly) * config.KELLY_FRACTION
    stake_pct = min(stake_pct, config.MAX_STAKE_PCT)
    return stake_pct * bankroll


def evaluate_market(market, model_home_prob, broker):
    """Given a Polymarket market dict (see polymarket_client.get_nfl_markets)
    and the model's estimated home win probability, place a paper bet on
    whichever side is mispriced enough, if we don't already hold a position.
    Returns the opened position, or None if no trade was made.
    """
    if broker.has_position(market["market_id"]):
        return None

    home_edge = model_home_prob - market["home_price"]
    away_edge = (1 - model_home_prob) - market["away_price"]

    if abs(home_edge) < config.EDGE_THRESHOLD and abs(away_edge) < config.EDGE_THRESHOLD:
        return None

    if home_edge >= away_edge and home_edge >= config.EDGE_THRESHOLD:
        side_team, price, model_prob, market_prob = (
            market["home_abbr"], market["home_price"], model_home_prob, market["home_price"])
    elif away_edge >= config.EDGE_THRESHOLD:
        side_team, price, model_prob, market_prob = (
            market["away_abbr"], market["away_price"], 1 - model_home_prob, market["away_price"])
    else:
        return None

    stake = kelly_stake(model_prob, price, broker.bankroll)
    if stake <= 1.0:  # not worth logging a sub-$1 bet
        return None

    return broker.place_bet(
        market_id=market["market_id"],
        question=market["question"],
        side_team=side_team,
        price=price,
        stake=stake,
        model_prob=model_prob,
        market_prob=market_prob,
    )


def evaluate_generic_market(raw_market, home_abbr, away_abbr, home_alias, away_alias, model, broker):
    """Prices every outcome of any tradable market family (moneyline, spread,
    total, team total, exact margin - see src/market_catalog.py) and paper-
    trades whichever outcome is mispriced enough, same Kelly sizing as
    evaluate_market(). Returns (opened_position_or_None, was_tradable: bool)
    - was_tradable distinguishes "priced but no edge" from "we have no model
    for this market type at all", so callers can log tracked-only markets
    separately without conflating them.
    """
    from src import market_catalog

    specs = market_catalog.parse_market(
        raw_market["sports_market_type"], raw_market["question"], raw_market.get("group_item_title"),
        raw_market["outcomes"], home_alias, away_alias,
    )
    if specs is None:
        return None, False

    if broker.has_position(raw_market["market_id"]):
        return None, True

    best = None  # (edge, outcome_name, spec, price, model_prob)
    for (outcome_name, spec), price in zip(specs, raw_market["prices"]):
        model_prob = model.price(spec, home_abbr, away_abbr)
        edge = model_prob - price
        if edge >= config.EDGE_THRESHOLD and (best is None or edge > best[0]):
            best = (edge, outcome_name, spec, price, model_prob)

    if best is None:
        return None, True

    _, outcome_name, spec, price, model_prob = best
    stake = kelly_stake(model_prob, price, broker.bankroll)
    if stake <= 1.0:
        return None, True

    position = broker.place_bet(
        market_id=raw_market["market_id"],
        question=raw_market["question"],
        side_team=outcome_name,
        price=price,
        stake=stake,
        model_prob=model_prob,
        market_prob=price,
        extra={"spec": list(spec), "home_abbr": home_abbr, "away_abbr": away_abbr,
               "sports_market_type": raw_market["sports_market_type"]},
    )
    return position, True
