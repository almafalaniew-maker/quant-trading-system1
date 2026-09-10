"""Is the $995k peak a real optimum or one lucky sequence of trades?

A robust setting degrades gently when you nudge it. A lucky path collapses,
because the luck lives in which specific trades got taken - and cash, slots and
rounding decide that. Perturbing things that should not matter much (a slightly
different opening balance, a basis point of slippage) is the cheapest test there
is: if the answer swings by hundreds of thousands, the peak was an accident.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import data as data_mod
from backtester import run_config
from strategy import StrategyConfig

WINDOW = ("2020-01-01", None)
frames = data_mod.load_csv_dir("bars")
benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ")}
uni = {s: f.loc[WINDOW[0]:WINDOW[1]] for s, f in frames.items()}
bm = {t: f.loc[WINDOW[0]:WINDOW[1]] for t, f in benchmarks.items()}

PEAK = StrategyConfig(name="the $995k peak", target_r=8.0, max_hold_bars=250,
                      risk_pct=0.010, max_open_positions=15)


def end_value(cfg, equity=100_000.0, **kw):
    perf, curve, blot = run_config(cfg, uni, bm, starting_equity=equity, **kw)
    return float(curve.iloc[-1]) / equity * 100_000.0, perf, blot


print("=" * 88)
print("TEST 1 - NUDGE THE OPENING BALANCE (normalised back to $100k)")
print("=" * 88)
print("  A real edge does not care whether you started with $98,000 or $102,000.\n")
vals = []
for eq in (95_000, 98_000, 99_000, 100_000, 101_000, 102_000, 105_000, 110_000):
    norm, perf, _ = end_value(PEAK, equity=float(eq))
    vals.append(norm)
    print(f"  start ${eq:>7,}  ->  ${norm:>11,.0f}   ({perf.trades} trades, "
          f"{perf.cagr:.1%} cagr)")
s = pd.Series(vals)
print(f"\n  spread: ${s.min():,.0f} to ${s.max():,.0f}"
      f"   median ${s.median():,.0f}   std ${s.std():,.0f}")
print(f"  the $995k result is {'AN OUTLIER' if s.median() < 700_000 else 'typical'} "
      f"of its own neighbourhood")

print("\n" + "=" * 88)
print("TEST 2 - NUDGE THE SLIPPAGE ASSUMPTION")
print("=" * 88)
print("  One basis point either way should not decide a seven-figure outcome.\n")
for bps in (3.0, 4.0, 5.0, 6.0, 7.0, 10.0):
    val, perf, _ = end_value(PEAK, cost_bps=bps)
    print(f"  {bps:>4.1f} bps  ->  ${val:>11,.0f}   ({perf.trades} trades)")

print("\n" + "=" * 88)
print("TEST 3 - WHERE DID THE MONEY ACTUALLY COME FROM?")
print("=" * 88)
_, perf, blot = end_value(PEAK)
blot = blot.sort_values("pnl", ascending=False)
total = blot["pnl"].sum()
print(f"  {len(blot)} trades, ${total:,.0f} net\n")
for n in (1, 3, 5, 10):
    share = blot.head(n)["pnl"].sum() / total
    print(f"    top {n:>2} trades: ${blot.head(n)['pnl'].sum():>10,.0f}  ({share:>5.0%} of all profit)")
print("\n  the five biggest:")
for _, t in blot.head(5).iterrows():
    print(f"    {t['symbol']:<6} {str(t['entry_date'])[:10]} -> {str(t['exit_date'])[:10]}  "
          f"${t['pnl']:>10,.0f}  {t['r_multiple']:+.2f}R")

print("\n  what happens if the single best trade had simply not been taken:")
without = total - blot.iloc[0]["pnl"]
print(f"    net profit falls from ${total:,.0f} to ${without:,.0f} "
      f"({(without/total - 1):+.0%})")

print("\n" + "=" * 88)
print("TEST 4 - FIT ON 2020-2023, VERIFY ON 2024-2026")
print("=" * 88)
print("  A setting that only wins on the full window was fitted to it.\n")
cands = [
    PEAK,
    PEAK.variant("target 6R", target_r=6.0),
    PEAK.variant("target 10R", target_r=10.0),
    PEAK.variant("target 12R", target_r=12.0),
    PEAK.variant("risk 0.5%", risk_pct=0.005),
    PEAK.variant("risk 1.5%", risk_pct=0.015),
    PEAK.variant("120 bars", max_hold_bars=120),
    PEAK.variant("stop 1.5xATR", atr_stop_mult=1.5),
    PEAK.variant("10 slots", max_open_positions=10),
]
print(f"  {'variant':<20}{'fit 20-23':>13}{'verify 24-26':>15}{'cagr 24-26':>13}{'maxDD':>9}")
rows = []
for cfg in cands:
    fu = {s: f.loc["2020-01-01":"2023-12-31"] for s, f in frames.items()}
    fb = {t: f.loc["2020-01-01":"2023-12-31"] for t, f in benchmarks.items()}
    p1, c1, _ = run_config(cfg, fu, fb, starting_equity=100_000.0)
    tu = {s: f.loc["2024-01-01":] for s, f in frames.items()}
    tb = {t: f.loc["2024-01-01":] for t, f in benchmarks.items()}
    p2, c2, _ = run_config(cfg, tu, tb, starting_equity=100_000.0)
    print(f"  {cfg.name:<20}{float(c1.iloc[-1]):>13,.0f}{float(c2.iloc[-1]):>15,.0f}"
          f"{p2.cagr*100:>12.1f}%{p2.max_drawdown*100:>8.1f}%", flush=True)
    rows.append({"variant": cfg.name, "fit": round(float(c1.iloc[-1])),
                 "verify": round(float(c2.iloc[-1])), "verify_cagr": round(p2.cagr*100, 1)})
pd.DataFrame(rows).to_csv("robustness_2020.csv", index=False)
