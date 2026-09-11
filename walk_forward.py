"""Walk-forward analysis: the test this project has never run.

Every result so far picked parameters with knowledge of the whole period, even
the "out-of-sample" ones - the split was chosen after seeing both halves. A walk
forward removes that. Each year, the parameters are chosen using only data that
existed at the time, then traded blind through the following year. Stitching
those untouched years together gives a track record that could actually have
been produced in real time.

If re-optimising each year beats holding one fixed setting, parameter selection
is adding information. If it does not, the sweeps were fitting noise.
"""

from __future__ import annotations

import itertools
import sys

import numpy as np
import pandas as pd

import data as data_mod
import metrics
from backtester import Backtester
from strategy import StrategyConfig, prepare_symbol

TRAIN_YEARS = 4
FIRST_TRADE_YEAR = 2011
LAST_YEAR = 2026

frames = data_mod.load_csv_dir("bars")
benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ")}

# A deliberately small grid. Every extra knob is another chance to fit noise,
# and the point here is to measure selection, not to win a sweep.
GRID = [
    StrategyConfig(name=f"t{t:g}_g{g[:3]}_s{s:g}", target_r=t, gap_mode=g,
                   atr_stop_mult=s, max_hold_bars=250, risk_pct=0.010,
                   max_open_positions=15)
    for t, g, s in itertools.product((4.0, 8.0, 12.0), ("ignored", "required"), (1.5, 2.0))
]
print(f"grid of {len(GRID)} candidates, {TRAIN_YEARS}-year training window\n", flush=True)

# prepare_symbol ignores target_r entirely, so the twelve candidates only need
# four distinct sets of frames - one per (stop width, gap mode) pair. Preparing
# one set per candidate would triple the memory for no extra information.
def prep_key(cfg):
    return (cfg.atr_stop_mult, cfg.gap_mode)

print("preparing indicator frames (one set per distinct stop/gap pair)...", flush=True)
PREP = {}
for cfg in GRID:
    key = prep_key(cfg)
    if key not in PREP:
        PREP[key] = {s: prepare_symbol(f, cfg) for s, f in frames.items()}
        print(f"  prepared stop={key[0]} gap={key[1]}", flush=True)
print("done\n", flush=True)


def score(cfg, lo, hi):
    """Train-window fitness. CAGR/maxDD rather than raw return, so a candidate
    cannot win the slot purely by having been the most leveraged."""
    uni = {s: f.loc[lo:hi] for s, f in frames.items()}
    bm = {t: f.loc[lo:hi] for t, f in benchmarks.items()}
    prep = {s: f.loc[lo:hi] for s, f in PREP[prep_key(cfg)].items()}
    engine = Backtester(cfg, starting_equity=100_000.0)
    curve, blot = engine.run(uni, bm, prepared=prep)
    perf = metrics.summarise(curve, blot)
    if perf.trades < 10 or perf.max_drawdown <= 0:
        return -np.inf, perf
    return perf.cagr / perf.max_drawdown, perf


def trade(cfg, lo, hi, equity):
    uni = {s: f.loc[lo:hi] for s, f in frames.items()}
    bm = {t: f.loc[lo:hi] for t, f in benchmarks.items()}
    prep = {s: f.loc[lo:hi] for s, f in PREP[prep_key(cfg)].items()}
    engine = Backtester(cfg, starting_equity=equity)
    curve, blot = engine.run(uni, bm, prepared=prep)
    return curve, blot


rows, curves, chosen = [], [], []
equity = 100_000.0
for year in range(FIRST_TRADE_YEAR, LAST_YEAR + 1):
    train_lo = f"{year - TRAIN_YEARS}-01-01"
    train_hi = f"{year - 1}-12-31"
    best, best_score = None, -np.inf
    for cfg in GRID:
        sc, _ = score(cfg, train_lo, train_hi)
        if sc > best_score:
            best, best_score = cfg, sc
    curve, blot = trade(best, f"{year}-01-01", f"{year}-12-31", equity)
    ret = float(curve.iloc[-1]) / equity - 1.0
    print(f"  {year}: trained {train_lo[:4]}-{train_hi[:4]} -> chose {best.name:<18} "
          f"| {len(blot):>3} trades | {ret:>7.1%} | ${float(curve.iloc[-1]):>11,.0f}",
          flush=True)
    rows.append({"year": year, "config": best.name, "trades": len(blot),
                 "return%": round(ret * 100, 1), "end_$": round(float(curve.iloc[-1]))})
    curves.append(curve)
    chosen.append(best.name)
    equity = float(curve.iloc[-1])

wf = pd.concat(curves)
wf = wf[~wf.index.duplicated(keep="first")]
table = pd.DataFrame(rows)
table.to_csv("walk_forward.csv", index=False)

print("\n" + "=" * 84)
print("WALK-FORWARD RESULT (parameters never saw the year they traded)")
print("=" * 84)
print(table.to_string(index=False))
print(f"\n  $100,000 -> ${float(wf.iloc[-1]):,.0f}")
print(f"  cagr {metrics.cagr(wf):.2%} | maxDD {metrics.max_drawdown(wf):.1%} "
      f"| sharpe {metrics.sharpe(wf):.2f}")
print(f"  winning years {(table['return%'] > 0).sum()} of {len(table)}")
print(f"\n  how often each candidate was chosen:")
print(pd.Series(chosen).value_counts().to_string())

# --- Benchmark: one fixed setting, never re-optimised ----------------------
print("\n" + "=" * 84)
print("VERSUS HOLDING ONE FIXED SETTING OVER THE SAME YEARS")
print("=" * 84)
lo, hi = f"{FIRST_TRADE_YEAR}-01-01", None
for cfg in GRID:
    uni = {s: f.loc[lo:hi] for s, f in frames.items()}
    bm = {t: f.loc[lo:hi] for t, f in benchmarks.items()}
    prep = {s: f.loc[lo:hi] for s, f in PREP[prep_key(cfg)].items()}
    engine = Backtester(cfg, starting_equity=100_000.0)
    c, b = engine.run(uni, bm, prepared=prep)
    p = metrics.summarise(c, b)
    print(f"  {cfg.name:<20} ${float(c.iloc[-1]):>11,.0f}  {p.cagr:>6.1%} cagr  "
          f"{p.max_drawdown:>5.1%} maxDD  {p.sharpe:.2f} sharpe", flush=True)
spy = benchmarks["SPY"]["close"].loc[lo:] / benchmarks["SPY"]["close"].loc[lo:].iloc[0]
print(f"  {'SPY buy & hold':<20} ${100_000 * float(spy.iloc[-1]):>11,.0f}  "
      f"{metrics.cagr(spy):>6.1%} cagr  {metrics.max_drawdown(spy):>5.1%} maxDD  "
      f"{metrics.sharpe(spy):.2f} sharpe")
wf.to_csv("walk_forward_equity.csv")
