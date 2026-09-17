"""Central configuration for NFLTrader."""

import os

# --- Polymarket ---
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
NFL_TAG_SLUG = "nfl"

# --- Elo model ---
ELO_DEFAULT_RATING = 1500.0
ELO_K_FACTOR = 20.0
ELO_HOME_ADVANTAGE = 65.0  # ~ historical NFL home-field edge in Elo points
ELO_MOV_MULTIPLIER = True  # scale K by margin of victory (538-style)

# --- Strategy / risk ---
EDGE_THRESHOLD = 0.05       # min |model_prob - market_prob| to consider a bet
KELLY_FRACTION = 0.25       # fraction of full Kelly stake actually risked
MAX_STAKE_PCT = 0.05        # never risk more than 5% of bankroll on one bet
STARTING_BANKROLL = 1000.0
MARKET_LOOKAHEAD_DAYS = 8   # only evaluate games starting within this window -
                             # lines for games many weeks out move a lot before
                             # kickoff, so committing capital to them this early
                             # isn't a real edge, just noise

# --- Live / CV win-probability blend ---
# how quickly the in-game score dominates the pregame Elo prior as the
# clock runs down (0 = ignore score, 1 = score fully dominates at 0:00)
WP_SCORE_WEIGHT_MAX = 0.9
WP_POSSESSION_BONUS = 0.03  # extra win prob credited to the team with the ball
WP_FIELD_POSITION_MAX = 0.08  # max extra win prob for having the ball at the goal line
INSIGHT_MIN_DELTA = 0.02      # smallest win-prob swing worth surfacing as an insight

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, "state")
DATA_DIR = os.path.join(BASE_DIR, "data")
ELO_RATINGS_PATH = os.path.join(STATE_DIR, "elo_ratings.json")
PORTFOLIO_PATH = os.path.join(STATE_DIR, "portfolio.json")
TRADE_LOG_PATH = os.path.join(STATE_DIR, "trade_log.csv")
GAMES_CSV_PATH = os.path.join(DATA_DIR, "games.csv")
ROI_CONFIG_PATH = os.path.join(DATA_DIR, "roi.json")

NFLVERSE_GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"

# Full team name (as Polymarket / nflverse tend to render it) -> standard abbreviation
TEAM_NAME_TO_ABBR = {
    "arizona cardinals": "ARI", "atlanta falcons": "ATL", "baltimore ravens": "BAL",
    "buffalo bills": "BUF", "carolina panthers": "CAR", "chicago bears": "CHI",
    "cincinnati bengals": "CIN", "cleveland browns": "CLE", "dallas cowboys": "DAL",
    "denver broncos": "DEN", "detroit lions": "DET", "green bay packers": "GB",
    "houston texans": "HOU", "indianapolis colts": "IND", "jacksonville jaguars": "JAX",
    "kansas city chiefs": "KC", "las vegas raiders": "LV", "los angeles chargers": "LAC",
    "los angeles rams": "LA", "miami dolphins": "MIA", "minnesota vikings": "MIN",
    "new england patriots": "NE", "new orleans saints": "NO", "new york giants": "NYG",
    "new york jets": "NYJ", "philadelphia eagles": "PHI", "pittsburgh steelers": "PIT",
    "san francisco 49ers": "SF", "seattle seahawks": "SEA", "tampa bay buccaneers": "TB",
    "tennessee titans": "TEN", "washington commanders": "WAS",
}
