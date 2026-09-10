"""Robustness checks on the gap requirement.

A filter that works at exactly one threshold and nowhere near it is a fluke.
A real effect shows a smooth dose-response: tighten the gate, the hit rate
climbs. This sweeps the threshold and reports the shape.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import data as data_mod
from backtester import run_config
from strategy import StrategyConfig

frames = data_mod.load_csv_dir("bars")
benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ")}
baseline = StrategyConfig(name="no_gap_gate")

rows = []
for threshold in [None, 0.005, 0.010, 0.015, 0.020, 0.025, 0.030, 0.040, 0.050]:
    if threshold is None:
        cfg = baseline
        label = "none"
    else:
        cfg = baseline.variant(f"gap>={threshold:.1%}", gap_mode="required",
                               min_gap_pct=threshold)
        label = f"{threshold:.1%}"
    perf, curve, blotter = run_config(cfg, frames, benchmarks)
    rows.append({
        "gap_gate": label, "trades": perf.trades, "win%": round(perf.win_rate * 100, 1),
        "exp_R": round(perf.expectancy_r, 3), "PF": round(perf.profit_factor, 2),
        "ret%": round(perf.total_return * 100, 1), "cagr%": round(perf.cagr * 100, 1),
        "maxDD%": round(perf.max_drawdown * 100, 1), "sharpe": round(perf.sharpe, 2),
    })
    print(f"  {label:>6}: {perf.trades:>4} trades  win {perf.win_rate:5.1%}  "
          f"exp {perf.expectancy_r:+.3f}R  ret {perf.total_return:7.1%}", flush=True)

sweep = pd.DataFrame(rows)
print("\n" + "=" * 88)
print("GAP THRESHOLD SWEEP")
print(sweep.to_string(index=False))
print("=" * 88)

# Is the trend monotone, or does 2.5% stand alone as a spike?
gated = sweep[sweep["gap_gate"] != "none"]
corr = np.corrcoef(
    [float(g.strip("%")) for g in gated["gap_gate"]], gated["win%"]
)[0, 1]
print(f"\ncorrelation between gap threshold and win rate: {corr:+.3f}")

# --- Does the edge survive splitting the sample in half? -------------------
print("\n" + "=" * 88)
print("SPLIT-SAMPLE: does the gap edge hold in both halves?")
print("=" * 88)
midpoint = benchmarks["SPY"].index[len(benchmarks["SPY"]) // 2]
print(f"first half: 2021-01-04 to {midpoint.date()} | second half: after {midpoint.date()}\n")

for half, lo, hi in (("first", None, midpoint), ("second", midpoint, None)):
    sliced = {s: df.loc[lo:hi] for s, df in frames.items()}
    bm = {t: df.loc[lo:hi] for t, df in benchmarks.items()}
    for cfg in (baseline, baseline.variant("gap>=2.5%", gap_mode="required")):
        perf, _, _ = run_config(cfg, sliced, bm)
        print(f"  {half:>6} half | {cfg.name:<12} {perf.trades:>4} trades  "
              f"win {perf.win_rate:5.1%}  exp {perf.expectancy_r:+.3f}R  "
              f"ret {perf.total_return:7.1%}  PF {perf.profit_factor:.2f}")
    print()

# --- Is the win-rate difference bigger than sampling noise? ----------------
print("=" * 88)
print("SIGNIFICANCE OF THE GAP EFFECT")
print("=" * 88)
_, _, base_trades = run_config(baseline, frames, benchmarks)
_, _, gap_trades = run_config(baseline.variant("gap", gap_mode="required"), frames, benchmarks)

for label, series in (("expectancy (R)", "r_multiple"),):
    a, b = base_trades[series], gap_trades[series]
    # Welch's t-test, written out rather than pulled from scipy.
    diff = b.mean() - a.mean()
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    t = diff / se
    print(f"{label}: baseline {a.mean():+.3f} (n={len(a)}), "
          f"gap {b.mean():+.3f} (n={len(b)})")
    print(f"  difference {diff:+.3f}R, standard error {se:.3f}, t = {t:.2f}")
    print(f"  -> {'not distinguishable from noise' if abs(t) < 1.96 else 'significant at the 5% level'}")

wins_a, wins_b = (base_trades["r_multiple"] > 0), (gap_trades["r_multiple"] > 0)
pa, pb = wins_a.mean(), wins_b.mean()
pooled = (wins_a.sum() + wins_b.sum()) / (len(wins_a) + len(wins_b))
se_p = np.sqrt(pooled * (1 - pooled) * (1 / len(wins_a) + 1 / len(wins_b)))
z = (pb - pa) / se_p
print(f"\nwin rate: baseline {pa:.1%}, gap {pb:.1%}, difference {pb - pa:+.1%}")
print(f"  z = {z:.2f} -> {'not distinguishable from noise' if abs(z) < 1.96 else 'significant at the 5% level'}")
