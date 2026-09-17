"""Simulated Polymarket portfolio: no real orders, no wallet - just tracks
what would have happened if we'd taken each signaled trade at the observed price.
"""

import csv
import json
import os
import time

import config


class PaperBroker:
    def __init__(self, bankroll=None, positions=None):
        self.bankroll = config.STARTING_BANKROLL if bankroll is None else bankroll
        # position key -> dict(market_id, question, side, team, entry_price, stake, shares, opened_at)
        self.positions = positions or {}

    def has_position(self, market_id):
        return market_id in self.positions

    def place_bet(self, market_id, question, side_team, price, stake, model_prob, market_prob, extra=None):
        """side_team: the team abbreviation (moneyline) or outcome label
        ("Over", "Yes", ...) we're buying YES shares on. `extra` is an
        optional dict of additional fields to store on the position - used
        by evaluate_generic_market to stash the pricing spec + home/away
        abbrs so cmd_settle can resolve it later without re-deriving it.
        """
        if price <= 0 or price >= 1:
            return None
        if stake > self.bankroll:
            stake = self.bankroll
        if stake <= 0:
            return None

        shares = stake / price
        self.bankroll -= stake
        position = {
            "market_id": market_id,
            "question": question,
            "side_team": side_team,
            "entry_price": price,
            "stake": stake,
            "shares": shares,
            "model_prob": model_prob,
            "market_prob": market_prob,
            "opened_at": time.time(),
            "status": "open",
        }
        if extra:
            position.update(extra)
        self.positions[market_id] = position
        self._log_trade(position, event="open")
        return position

    def settle_market(self, market_id, winner_abbr):
        """Moneyline-style settlement: side_team is a team abbreviation,
        winner_abbr is which team actually won."""
        position = self.positions.get(market_id)
        if not position or position["status"] != "open":
            return None
        return self.settle_outcome(market_id, won=(position["side_team"] == winner_abbr))

    def settle_outcome(self, market_id, won):
        """Generic settlement: caller has already determined whether this
        position's specific outcome (moneyline side, spread cover, total
        over/under, margin bucket, ...) actually happened."""
        position = self.positions.get(market_id)
        if not position or position["status"] != "open":
            return None

        payout = position["shares"] * 1.0 if won else 0.0
        self.bankroll += payout
        position["status"] = "settled"
        position["won"] = won
        position["payout"] = payout
        position["pnl"] = payout - position["stake"]
        self._log_trade(position, event="settle")
        return position

    def open_positions(self):
        return [p for p in self.positions.values() if p["status"] == "open"]

    def summary(self):
        settled = [p for p in self.positions.values() if p["status"] == "settled"]
        realized_pnl = sum(p["pnl"] for p in settled)
        return {
            "bankroll": self.bankroll,
            "open_positions": len(self.open_positions()),
            "settled_bets": len(settled),
            "wins": sum(1 for p in settled if p["won"]),
            "losses": sum(1 for p in settled if not p["won"]),
            "realized_pnl": realized_pnl,
            "roi_pct": (realized_pnl / config.STARTING_BANKROLL) * 100,
        }

    def _log_trade(self, position, event):
        os.makedirs(config.STATE_DIR, exist_ok=True)
        file_exists = os.path.exists(config.TRADE_LOG_PATH)
        with open(config.TRADE_LOG_PATH, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "event", "market_id", "question", "side_team",
                                  "price", "stake", "model_prob", "market_prob", "pnl"])
            writer.writerow([
                time.strftime("%Y-%m-%d %H:%M:%S"), event, position["market_id"],
                position["question"], position["side_team"], position["entry_price"],
                position["stake"], position["model_prob"], position["market_prob"],
                position.get("pnl", ""),
            ])

    def save(self, path=config.PORTFOLIO_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"bankroll": self.bankroll, "positions": self.positions}, f, indent=2)

    @classmethod
    def load(cls, path=config.PORTFOLIO_PATH):
        if not os.path.exists(path):
            return cls()
        with open(path) as f:
            data = json.load(f)
        return cls(bankroll=data.get("bankroll"), positions=data.get("positions", {}))
