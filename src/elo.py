"""A 538-style Elo rating system for NFL teams."""

import json
import math
import os

import config


class EloRatings:
    def __init__(self, ratings=None):
        self.ratings = dict(ratings) if ratings else {}

    def get(self, team):
        return self.ratings.get(team, config.ELO_DEFAULT_RATING)

    def expected_home_win_prob(self, home, away):
        home_rating = self.get(home) + config.ELO_HOME_ADVANTAGE
        away_rating = self.get(away)
        return 1.0 / (1.0 + 10 ** ((away_rating - home_rating) / 400.0))

    def update(self, home, away, home_score, away_score):
        """Update ratings in place from a final score. Returns (new_home, new_away)."""
        expected_home = self.expected_home_win_prob(home, away)
        if home_score > away_score:
            actual_home = 1.0
        elif home_score < away_score:
            actual_home = 0.0
        else:
            actual_home = 0.5

        k = config.ELO_K_FACTOR
        if config.ELO_MOV_MULTIPLIER and home_score != away_score:
            margin = abs(home_score - away_score)
            elo_diff_winner = (self.get(home) - self.get(away)) if actual_home == 1.0 \
                else (self.get(away) - self.get(home))
            # 538 NFL Elo margin-of-victory multiplier
            k *= math.log(margin + 1) * (2.2 / ((elo_diff_winner * 0.001) + 2.2))

        delta = k * (actual_home - expected_home)
        home_rating = self.get(home) + delta
        away_rating = self.get(away) - delta
        self.ratings[home] = home_rating
        self.ratings[away] = away_rating
        return home_rating, away_rating

    def save(self, path=config.ELO_RATINGS_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.ratings, f, indent=2, sort_keys=True)

    @classmethod
    def load(cls, path=config.ELO_RATINGS_PATH):
        if not os.path.exists(path):
            return cls()
        with open(path) as f:
            return cls(json.load(f))
