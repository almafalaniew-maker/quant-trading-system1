"""Re-run after the engine fixes, with the tuning window held out.

Four defects were repaired: entries are sized down rather than dropped when cash
is short, a zero scale fraction no longer sells a share, the trailing stop can be
armed independently of a scale-out, and the hold limit counts trading bars.

The arms below test the one thing the diagnosis pointed at: the calendar time
stop was closing trades that averaged +1.68R to +3.50R and were 94-98%
profitable. A trailing stop should exit those on price instead of on a clock.
"""

from __future__ import annotations

import pandas as pd

import data as data_mod
import metrics
from backtester import run_config
from strategy import StrategyConfig

START = 100_000.0
frames = data_mod.load_csv_dir("bars")
benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ")}

BASE = StrategyConfig(name="baseline 4R")
LONG = dict(target_r=99.0, max_hold_bars=500)      # target out of reach: price exits

ARMS = [
    BASE,
    BASE.variant("8R target", target_r=8.0),
    BASE.variant("8R + trail from 2R", target_r=8.0, trail_from_r=2.0,
                 trail_atr_mult=3.0, max_hold_bars=500),
    BASE.variant("trail from entry", trail_from_r=0.0, trail_atr_mult=3.0, **LONG),
    BASE.variant("trail from 1R", trail_from_r=1.0, trail_atr_mult=3.0, **LONG),
    BASE.variant("trail from 2R", trail_from_r=2.0, trail_atr_mult=3.0, **LONG),
    BASE.variant("trail 2R + gap>=2.5%", trail_from_r=2.0, trail_atr_mult=3.0,
                 gap_mode="required", **LONG),
    BASE.variant("trail 2R + 10% cap", trail_from_r=2.0, trail_atr_mult=3.0,
                 max_position_pct=0.10, **LONG),
]


def window(label, lo, hi):
    uni = {s: f.loc[lo:hi] for s, f in frames.items()}
    bm = {t: f.loc[lo:hi] for t, f in benchmarks.items()}
    print(f"\n{'=' * 96}\n{label}\n{'=' * 96}")
    print(f"  {'variant':<24}{'trades':>7}{'win%':>7}{'end $':>12}{'cagr%':>8}"
          f"{'maxDD%':>8}{'sharpe':>8}{'timestop%':>10}")
    rows = []
    for cfg in ARMS:
        perf, curve, blot = run_config(cfg, uni, bm, starting_equity=START)
        ts = 0.0
        if not blot.empty:
            ts = (blot["exit_reason"] == "time_stop").mean() * 100
        print(f"  {cfg.name:<24}{perf.trades:>7}{perf.win_rate * 100:>7.1f}"
              f"{float(curve.iloc[-1]):>12,.0f}{perf.cagr * 100:>8.1f}"
              f"{perf.max_drawdown * 100:>8.1f}{perf.sharpe:>8.2f}{ts:>10.0f}",
              flush=True)
        rows.append({"window": label, "variant": cfg.name, "trades": perf.trades,
                     "win%": round(perf.win_rate * 100, 1),
                     "end_$": round(float(curve.iloc[-1])),
                     "cagr%": round(perf.cagr * 100, 1),
                     "maxDD%": round(perf.max_drawdown * 100, 1),
                     "sharpe": round(perf.sharpe, 2), "timestop%": round(ts)})
    spy = bm["SPY"]["close"] / bm["SPY"]["close"].iloc[0]
    print(f"  {'SPY buy & hold':<24}{'-':>7}{'-':>7}{START * float(spy.iloc[-1]):>12,.0f}"
          f"{metrics.cagr(spy) * 100:>8.1f}{metrics.max_drawdown(spy) * 100:>8.1f}"
          f"{metrics.sharpe(spy):>8.2f}")
    return rows


rows = []
rows += window("OUT-OF-SAMPLE   2006-01-03 to 2020-12-31", None, "2020-12-31")
rows += window("TUNING WINDOW   2021-01-04 to 2026-09-09", "2021-01-01", None)
rows += window("FULL 20 YEARS   2006-01-03 to 2026-09-09", None, None)
pd.DataFrame(rows).to_csv("results_fixed.csv", index=False)
print("\nwrote results_fixed.csv")
