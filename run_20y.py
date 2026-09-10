"""Twenty-year run: the diagnosed fix, tested out-of-sample and by holding period.

The diagnosis said the 4R target was the leak - 104 trades hit it and the median
of those went on to 7.3R. The fix raises the cap. Since that number was chosen by
looking at 2021-2026, the 2006-2020 stretch is a genuine out-of-sample test of it.
"""

from __future__ import annotations

import pandas as pd

import data as data_mod
import metrics
from backtester import run_config
from strategy import StrategyConfig

START_EQUITY = 100_000.0

frames = data_mod.load_csv_dir("bars")
benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ")}
cal = benchmarks["SPY"].index
print(f"universe {len(frames)} names | {cal[0].date()} -> {cal[-1].date()} "
      f"({len(cal):,} sessions)\n")

BASE = StrategyConfig(name="baseline 4R target")
FIXED = BASE.variant("FIXED: gap>=2.5% + 12R cap", gap_mode="required", target_r=12.0)


def slice_all(lo=None, hi=None):
    return ({s: f.loc[lo:hi] for s, f in frames.items()},
            {t: f.loc[lo:hi] for t, f in benchmarks.items()})


def bh_equal_weight(uni, bm):
    c = bm["SPY"].index
    curves = []
    for f in uni.values():
        if len(f) < 2:
            continue
        curves.append((f["close"] / f["close"].iloc[0]).reindex(c).ffill().bfill())
    return pd.concat(curves, axis=1).mean(axis=1)


# --- 1. Out-of-sample: was the fix chosen on 2021-26 any good before it? ----
print("=" * 84)
print("OUT-OF-SAMPLE CHECK  (2006-01-03 to 2020-12-31, before the tuning window)")
print("=" * 84)
uni, bm = slice_all(None, "2020-12-31")
print(f"  {'variant':<30}{'trades':>7}{'win%':>7}{'ret%':>10}{'cagr%':>8}{'maxDD%':>8}{'sharpe':>8}")
for cfg in [BASE,
            BASE.variant("target 8R", target_r=8.0),
            BASE.variant("target 12R", target_r=12.0),
            BASE.variant("gap>=2.5% only", gap_mode="required"),
            FIXED]:
    perf, _, _ = run_config(cfg, uni, bm, starting_equity=START_EQUITY)
    print(f"  {cfg.name:<30}{perf.trades:>7}{perf.win_rate*100:>7.1f}"
          f"{perf.total_return*100:>10.1f}{perf.cagr*100:>8.1f}"
          f"{perf.max_drawdown*100:>8.1f}{perf.sharpe:>8.2f}", flush=True)

# --- 2. By holding period, in dollars --------------------------------------
WINDOWS = [("1 year", "2025-09-10"), ("3 years", "2023-09-11"),
           ("10 years", "2016-09-12"), ("20 years", None)]

print("\n" + "=" * 84)
print(f"WHAT IT TRADED AND WHAT IT MADE  (starting with ${START_EQUITY:,.0f})")
print("=" * 84)

rows = []
blotters = {}
for label, lo in WINDOWS:
    uni, bm = slice_all(lo, None)
    for cfg in (BASE, FIXED):
        perf, curve, blot = run_config(cfg, uni, bm, starting_equity=START_EQUITY)
        end_equity = float(curve.iloc[-1])
        rows.append({
            "window": label, "strategy": cfg.name,
            "trades": perf.trades,
            "win%": round(perf.win_rate * 100, 1),
            "end_$": round(end_equity),
            "profit_$": round(end_equity - START_EQUITY),
            "ret%": round(perf.total_return * 100, 1),
            "cagr%": round(perf.cagr * 100, 1),
            "maxDD%": round(perf.max_drawdown * 100, 1),
            "worst_$": round(START_EQUITY * perf.max_drawdown),
            "sharpe": round(perf.sharpe, 2),
        })
        if cfg is FIXED:
            blotters[label] = blot
        print(f"  {label:<9} {cfg.name:<30} {perf.trades:>5} trades  "
              f"${end_equity:>12,.0f}  {perf.cagr*100:>6.1f}% cagr", flush=True)
    # benchmarks for the same window
    bh = bh_equal_weight(uni, bm)
    spy = (bm["SPY"]["close"] / bm["SPY"]["close"].iloc[0])
    for name, c in (("SPY buy & hold", spy), ("equal-weight buy & hold", bh)):
        rows.append({
            "window": label, "strategy": name, "trades": 0, "win%": float("nan"),
            "end_$": round(START_EQUITY * float(c.iloc[-1])),
            "profit_$": round(START_EQUITY * (float(c.iloc[-1]) - 1)),
            "ret%": round((float(c.iloc[-1]) - 1) * 100, 1),
            "cagr%": round(metrics.cagr(c) * 100, 1),
            "maxDD%": round(metrics.max_drawdown(c) * 100, 1),
            "worst_$": round(START_EQUITY * metrics.max_drawdown(c)),
            "sharpe": round(metrics.sharpe(c), 2),
        })

table = pd.DataFrame(rows)
print("\n" + "=" * 110)
for label, _ in WINDOWS:
    print(f"\n--- {label} (to 2026-09-09) ---")
    print(table[table["window"] == label].drop(columns="window").to_string(index=False))
table.to_csv("results_20y.csv", index=False)

# --- 3. What actually got traded over 20 years -----------------------------
blot = blotters["20 years"]
print("\n" + "=" * 84)
print("WHAT THE FIXED SYSTEM TRADED OVER 20 YEARS")
print("=" * 84)
by_symbol = (blot.groupby("symbol")
             .agg(trades=("pnl", "size"), pnl=("pnl", "sum"),
                  win_rate=("r_multiple", lambda s: (s > 0).mean()),
                  best_R=("r_multiple", "max"))
             .sort_values("pnl", ascending=False))
print(f"\ntotal {len(blot)} trades across {blot['symbol'].nunique()} names")
print(f"\ntop 12 contributors:")
print(by_symbol.head(12).round(2).to_string())
print(f"\nworst 6:")
print(by_symbol.tail(6).round(2).to_string())
top10 = by_symbol.head(10)["pnl"].sum()
print(f"\ntop 10 names produced ${top10:,.0f} of ${blot['pnl'].sum():,.0f} total "
      f"({top10 / blot['pnl'].sum():.0%})")
print(f"\nexit reasons:")
print(blot["exit_reason"].value_counts().to_string())
print(f"\ntrades per calendar year:")
print(blot.groupby(blot["entry_date"].dt.year).size().to_string())
