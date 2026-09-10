"""Separate what generalises from what was fitted to 2021-2026.

The 12R cap and the 2.5% gap gate were both chosen by looking at 2021-2026.
On 2006-2020 the raised target still helped and the gap gate did not, so they
are not the same kind of finding and should not be shipped as one change.

The 12R run also exposed a structural problem: it exited on the 120-day time
stop 253 times and on the target 7 times. A 12R cap is effectively no target,
which makes an arbitrary calendar limit the real exit rule. These arms test
replacing that with a trail.
"""

from __future__ import annotations

import pandas as pd

import data as data_mod
from backtester import run_config
from strategy import StrategyConfig

frames = data_mod.load_csv_dir("bars")
benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ")}

BASE = StrategyConfig(name="baseline 4R")
ARMS = [
    BASE,
    BASE.variant("8R target", target_r=8.0),
    BASE.variant("8R + 250d hold", target_r=8.0, max_hold_days=250),
    BASE.variant("no target, trail 3xATR", exit_mode="scale_out", scale_fraction=0.0,
                 trail_atr_mult=3.0, max_hold_days=250),
    BASE.variant("8R + gap>=2.5%", target_r=8.0, gap_mode="required"),
    BASE.variant("8R + gap ranked", target_r=8.0, gap_mode="bonus"),
]

def run_window(label, lo, hi):
    uni = {s: f.loc[lo:hi] for s, f in frames.items()}
    bm = {t: f.loc[lo:hi] for t, f in benchmarks.items()}
    print(f"\n{'=' * 92}\n{label}\n{'=' * 92}")
    print(f"  {'variant':<26}{'trades':>7}{'win%':>7}{'end $':>12}"
          f"{'ret%':>9}{'cagr%':>8}{'maxDD%':>8}{'sharpe':>8}")
    out = []
    for cfg in ARMS:
        perf, curve, blot = run_config(cfg, uni, bm, starting_equity=100_000.0)
        print(f"  {cfg.name:<26}{perf.trades:>7}{perf.win_rate*100:>7.1f}"
              f"{float(curve.iloc[-1]):>12,.0f}{perf.total_return*100:>9.1f}"
              f"{perf.cagr*100:>8.1f}{perf.max_drawdown*100:>8.1f}{perf.sharpe:>8.2f}",
              flush=True)
        out.append({"window": label, "variant": cfg.name, "trades": perf.trades,
                    "win%": round(perf.win_rate*100, 1),
                    "end_$": round(float(curve.iloc[-1])),
                    "cagr%": round(perf.cagr*100, 1),
                    "maxDD%": round(perf.max_drawdown*100, 1),
                    "sharpe": round(perf.sharpe, 2)})
    return out

rows = []
rows += run_window("OUT-OF-SAMPLE  2006-01-03 to 2020-12-31", None, "2020-12-31")
rows += run_window("TUNING WINDOW  2021-01-04 to 2026-09-09", "2021-01-01", None)
rows += run_window("FULL 20 YEARS  2006-01-03 to 2026-09-09", None, None)
pd.DataFrame(rows).to_csv("final_fix.csv", index=False)
print("\nwrote final_fix.csv")
