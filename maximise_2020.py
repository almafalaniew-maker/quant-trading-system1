"""Maximise money over 2020-2026, with an honest split inside the window.

Tuning on the whole window leaves nothing to check the result against, and this
window is unusually kind - one bad year in seven. So every candidate is also run
on 2020-2023 (fit) and 2024-2026 (verify) separately. A setting that only wins
on the full window is a setting fitted to it.
"""

from __future__ import annotations

import pandas as pd

import data as data_mod
import metrics
from backtester import run_config
from strategy import StrategyConfig

START = 100_000.0
FULL, FIT, TEST = ("2020-01-01", None), ("2020-01-01", "2023-12-31"), ("2024-01-01", None)

frames = data_mod.load_csv_dir("bars")
benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ")}


def run(cfg, span, equity=START):
    lo, hi = span
    uni = {s: f.loc[lo:hi] for s, f in frames.items()}
    bm = {t: f.loc[lo:hi] for t, f in benchmarks.items()}
    perf, curve, blot = run_config(cfg, uni, bm, starting_equity=equity)
    return perf, float(curve.iloc[-1]), blot


def sweep(title, cfgs):
    print(f"\n{'=' * 96}\n{title}\n{'=' * 96}")
    print(f"  {'variant':<32}{'end $':>12}{'cagr%':>8}{'maxDD%':>8}"
          f"{'sharpe':>8}{'trades':>8}{'win%':>7}")
    out = []
    for cfg in cfgs:
        perf, end, _ = run(cfg, FULL)
        print(f"  {cfg.name:<32}{end:>12,.0f}{perf.cagr*100:>8.1f}"
              f"{perf.max_drawdown*100:>8.1f}{perf.sharpe:>8.2f}"
              f"{perf.trades:>8}{perf.win_rate*100:>7.1f}", flush=True)
        out.append((cfg, end, perf))
    return out


# Starting point: the configuration that won over twenty years.
BEST20 = StrategyConfig(name="20-year winner", target_r=8.0, max_hold_bars=250,
                        risk_pct=0.010, max_open_positions=15)

# --- Stage A: one lever at a time -----------------------------------------
sweep("STAGE A1 - PROFIT TARGET", [
    BEST20.variant(f"target {t:g}R", target_r=t) for t in (4, 6, 8, 10, 12, 16)
] + [BEST20.variant("no target (trail 3xATR)", target_r=99.0, trail_from_r=1.0,
                    trail_atr_mult=3.0)])

sweep("STAGE A2 - RISK PER TRADE", [
    BEST20.variant(f"risk {r:.2%}", risk_pct=r)
    for r in (0.005, 0.010, 0.015, 0.020, 0.025, 0.030)])

sweep("STAGE A3 - HOW LONG TO HOLD", [
    BEST20.variant(f"{h} bars", max_hold_bars=h) for h in (83, 120, 180, 250, 400)])

sweep("STAGE A4 - CONCURRENT POSITIONS", [
    BEST20.variant(f"{n} slots", max_open_positions=n) for n in (8, 10, 15, 20, 25)])

sweep("STAGE A5 - ENTRY FILTERS", [
    BEST20.variant("no gap filter", gap_mode="ignored"),
    BEST20.variant("gap required 2.5%", gap_mode="required"),
    BEST20.variant("gap ranked first", gap_mode="bonus"),
    BEST20.variant("no trend filter", require_trend=False),
    BEST20.variant("breakout 10-day", breakout_window=10),
    BEST20.variant("breakout 20-day", breakout_window=20),
])

sweep("STAGE A6 - REGIME GATE AND STOP WIDTH", [
    BEST20.variant("SPY 50-day (current)"),
    BEST20.variant("no regime gate", regime_mode="none"),
    BEST20.variant("SPY+QQQ strict", regime_mode="dual_index_strict"),
    BEST20.variant("stop 1.5xATR", atr_stop_mult=1.5),
    BEST20.variant("stop 2.5xATR", atr_stop_mult=2.5),
    BEST20.variant("stop 3.0xATR", atr_stop_mult=3.0),
])

sweep("STAGE A7 - POSITION CAP", [
    BEST20.variant(f"cap {c:.0%}", max_position_pct=c)
    for c in (0.10, 0.20, 0.30, 0.40)])
