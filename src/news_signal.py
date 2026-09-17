"""Injury/news signal from X (Twitter) - a genuinely different kind of edge
than anything else in this project: a star player getting hurt or ruled out
is information no score feed or on-field CV can see, since it hasn't
happened on the field yet. This is NOT a speed play - ESPN/the CV pipeline
will always beat X on latency for something that already happened during a
play. It's for information that originates off the field entirely (beat
reporter injury news, inactive lists, coaching decisions).

Needs a paid X API bearer token (X_BEARER_TOKEN env var) - this project
can't obtain one on your behalf. Without one, `is_configured()` returns
False and callers should just skip this source rather than erroring.
"""

import os
import re

import requests

SEARCH_URL = "https://api.x.com/2/tweets/search/recent"

# Only these handles are queried - open keyword search on X is extremely
# noisy (rumor, fan speculation, bots); beat reporters and team-affiliated
# insiders are a much higher-precision source for real injury/inactive news.
TRUSTED_NFL_INSIDERS = [
    "RapSheet", "AdamSchefter", "TomPelissero", "MikeGarafolo", "FieldYates",
]

_INJURY_KEYWORDS = re.compile(
    r"\b(out|questionable|doubtful|ruled out|inactive|carted off|"
    r"injury|injured|concussion protocol|will not return)\b", re.IGNORECASE)


def is_configured():
    return bool(os.environ.get("X_BEARER_TOKEN"))


def search_injury_news(team_or_player, max_results=10):
    """Recent posts from trusted insiders mentioning the given team/player
    and an injury-related keyword. Returns [] if X_BEARER_TOKEN isn't set,
    rather than raising, so callers can treat this as best-effort.
    """
    token = os.environ.get("X_BEARER_TOKEN")
    if not token:
        return []

    from_clause = " OR ".join(f"from:{handle}" for handle in TRUSTED_NFL_INSIDERS)
    query = f"({from_clause}) {team_or_player}"
    resp = requests.get(
        SEARCH_URL,
        headers={"Authorization": f"Bearer {token}"},
        params={"query": query, "max_results": max_results, "tweet.fields": "author_id,created_at"},
        timeout=15,
    )
    resp.raise_for_status()
    tweets = resp.json().get("data", [])
    return [t for t in tweets if _INJURY_KEYWORDS.search(t.get("text", ""))]
