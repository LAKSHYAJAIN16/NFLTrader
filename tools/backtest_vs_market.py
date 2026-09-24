"""Does the model beat the market's closing line?

    python tools/backtest_vs_market.py

Walk-forward over nflverse history (which carries each game's closing spread
and total): every prediction uses only games before it, and the margin/total
regressions are fit on seasons before the evaluation window. Reports RMSE of
model vs. closing line, the win rate of betting the model's side when it
disagrees with the line by N+ points (52.4% breaks even at -110), and whether
blending any of the model into the line helps. Re-run after any model change.
"""
import csv
import math
import sys

sys.path.insert(0, ".")
import config
from src.elo import EloRatings
from src.scoring_model import TeamScoring, _fit_line

EVAL_FROM = 2012
rows = [r for r in csv.DictReader(open(config.GAMES_CSV_PATH, encoding="utf-8")) if r["home_score"]]
rows.sort(key=lambda r: (int(r["season"]), int(r["week"] or 0), r["gameday"]))

elo, ts = EloRatings(), TeamScoring()
records = []
for r in rows:
    h, a = r["home_team"], r["away_team"]
    hs, as_ = float(r["home_score"]), float(r["away_score"])
    neutral = r["location"] == "Neutral"
    hfa = 0 if neutral else config.ELO_HOME_ADVANTAGE
    records.append({
        "season": int(r["season"]),
        "elo_diff": elo.get(h) + hfa - elo.get(a),
        "raw_total": sum(ts.expected(h, a)),
        "margin": hs - as_, "total": hs + as_,
        "spread_line": float(r["spread_line"]), "total_line": float(r["total_line"]),
    })
    elo.update(h, a, hs, as_)
    ts.update(int(r["season"]), h, a, hs, as_)

train = [x for x in records if 2002 <= x["season"] < EVAL_FROM]
test = [x for x in records if x["season"] >= EVAL_FROM]
m_slope, m_int = _fit_line([x["elo_diff"] for x in train], [x["margin"] for x in train])
t_slope, t_int = _fit_line([x["raw_total"] for x in train], [x["total"] for x in train])
for x in test:
    x["m_pred"] = m_slope * x["elo_diff"] + m_int
    x["t_pred"] = t_slope * x["raw_total"] + t_int

rmse = lambda errs: math.sqrt(sum(e * e for e in errs) / len(errs))
print(f"{len(test)} games, {EVAL_FROM}-2026\n")
print("                 model    closing line")
print(f"margin RMSE     {rmse([x['margin'] - x['m_pred'] for x in test]):6.2f}   {rmse([x['margin'] - x['spread_line'] for x in test]):6.2f}")
print(f"total RMSE      {rmse([x['total'] - x['t_pred'] for x in test]):6.2f}   {rmse([x['total'] - x['total_line'] for x in test]):6.2f}")


def bets(kind, min_gap):
    wins = losses = 0
    for x in test:
        if kind == "spread":
            gap, outcome = x["m_pred"] - x["spread_line"], x["margin"] - x["spread_line"]
        else:
            gap, outcome = x["t_pred"] - x["total_line"], x["total"] - x["total_line"]
        if abs(gap) < min_gap or outcome == 0:
            continue
        if (gap > 0) == (outcome > 0):
            wins += 1
        else:
            losses += 1
    n = wins + losses
    return n, (wins / n if n else float("nan"))


print("\nBet the model's side when it disagrees with the closing line (need 52.4% to profit at -110):")
for kind in ("spread", "total"):
    for gap in (1, 2, 3, 4, 6):
        n, rate = bets(kind, gap)
        print(f"  {kind:6} gap >= {gap} pts: {n:5} bets, win rate {rate * 100:5.1f}%")

# Blend: does a little of the model on top of the line help at all?
print("\nBlend  line + w * (model - line), margin RMSE:")
for w in (0.0, 0.1, 0.2, 0.3):
    print(f"  w={w:.1f}: {rmse([x['margin'] - (x['spread_line'] + w * (x['m_pred'] - x['spread_line'])) for x in test]):.3f}"
          f"   totals: {rmse([x['total'] - (x['total_line'] + w * (x['t_pred'] - x['total_line'])) for x in test]):.3f}")
