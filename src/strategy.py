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
