"""Rank candidates by their MEDIAN outcome, not their luckiest one.

A single backtest is one path. Which trades get taken depends on cash, slots and
rounding, so nudging the opening balance reshuffles the path without changing
the edge. Running each candidate across many opening balances turns one number
into a distribution, and the median of that distribution is a far more honest
estimate of what the setting is worth than its best draw.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import data as data_mod
import metrics
from backtester import run_config
from strategy import StrategyConfig

frames = data_mod.load_csv_dir("bars")
benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ")}
uni = {s: f.loc["2020-01-01":] for s, f in frames.items()}
bm = {t: f.loc["2020-01-01":] for t, f in benchmarks.items()}

# Opening balances that should not change the edge, only the path.
STARTS = [92_000, 94_000, 96_000, 98_000, 100_000, 102_000,
          104_000, 106_000, 108_000, 110_000, 115_000]

BASE = StrategyConfig(name="8R/250/1.0%/15", target_r=8.0, max_hold_bars=250,
                      risk_pct=0.010, max_open_positions=15)

CANDIDATES = [
    BASE,
    BASE.variant("8R/250/1.0%/10 slots", max_open_positions=10),
    BASE.variant("8R/120/1.0%/15", max_hold_bars=120),
    BASE.variant("8R/250/1.5%/15", risk_pct=0.015),
    BASE.variant("8R/250/0.5%/15", risk_pct=0.005),
    BASE.variant("8R/250/1.0%/15 stop1.5", atr_stop_mult=1.5),
    BASE.variant("10R/250/1.0%/15", target_r=10.0),
    BASE.variant("8R/250/1.0%/15 gap", gap_mode="required"),
]

print("=" * 100)
print("EACH CANDIDATE ACROSS 11 OPENING BALANCES  (all normalised back to $100k)")
print("=" * 100)
print(f"  {'candidate':<26}{'median':>11}{'mean':>11}{'worst':>11}{'best':>11}"
      f"{'spread':>10}{'med cagr':>10}{'med DD':>9}")

rows = []
for cfg in CANDIDATES:
    ends, cagrs, dds = [], [], []
    for eq in STARTS:
        perf, curve, _ = run_config(cfg, uni, bm, starting_equity=float(eq))
        ends.append(float(curve.iloc[-1]) / eq * 100_000.0)
        cagrs.append(perf.cagr)
        dds.append(perf.max_drawdown)
    e = pd.Series(ends)
    print(f"  {cfg.name:<26}{e.median():>11,.0f}{e.mean():>11,.0f}{e.min():>11,.0f}"
          f"{e.max():>11,.0f}{e.max()/e.min():>9.2f}x{np.median(cagrs)*100:>9.1f}%"
          f"{np.median(dds)*100:>8.1f}%", flush=True)
    rows.append({"candidate": cfg.name, "median_$": round(e.median()),
                 "mean_$": round(e.mean()), "worst_$": round(e.min()),
                 "best_$": round(e.max()), "spread_x": round(e.max()/e.min(), 2),
                 "median_cagr%": round(np.median(cagrs)*100, 1),
                 "median_maxDD%": round(np.median(dds)*100, 1)})

table = pd.DataFrame(rows).sort_values("median_$", ascending=False)
table.to_csv("median_ranking_2020.csv", index=False)

print("\n" + "=" * 100)
print("RANKED BY MEDIAN (the honest ordering)")
print("=" * 100)
print(table.to_string(index=False))

spy = bm["SPY"]["close"] / bm["SPY"]["close"].iloc[0]
print(f"\n  SPY buy & hold over the same window: ${100_000 * float(spy.iloc[-1]):,.0f}"
      f"   {metrics.cagr(spy):.1%} cagr   {metrics.max_drawdown(spy):.1%} maxDD")

best = table.iloc[0]
print(f"\n  Best by median: {best['candidate']}")
print(f"    expect around ${best['median_$']:,.0f} ({best['median_cagr%']}% a year),")
print(f"    anywhere from ${best['worst_$']:,.0f} to ${best['best_$']:,.0f} "
      f"depending purely on which path you land on.")
