"""The trail was the wrong fix. Two cheaper ones are still untested.

The 8R target won out-of-sample, in the tuning window and over twenty years, so
it is the thing to build on rather than replace. Two leads remain:

  * The 10% notional cap improved the trailing arm from $621k to $741k over
    twenty years, which says the book was too concentrated to hold ten positions
    without starving itself of cash. That was never tested against the 8R target.
  * The hold limit still closes 27% of 8R trades, and those average +2.99R. The
    trail was a bad way to free them. Simply giving them more bars may not be.
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
EIGHT = StrategyConfig(name="8R target", target_r=8.0)

ARMS = [
    EIGHT,
    # How concentrated should one position be allowed to get?
    EIGHT.variant("8R + 15% cap", max_position_pct=0.15),
    EIGHT.variant("8R + 12% cap", max_position_pct=0.12),
    EIGHT.variant("8R + 10% cap", max_position_pct=0.10),
    EIGHT.variant("8R + 8% cap", max_position_pct=0.08),
    # How long should a trade be given?
    EIGHT.variant("8R + 120 bars", max_hold_bars=120),
    EIGHT.variant("8R + 180 bars", max_hold_bars=180),
    EIGHT.variant("8R + 250 bars", max_hold_bars=250),
    # And the two together.
    EIGHT.variant("8R + 10% cap + 180 bars", max_position_pct=0.10, max_hold_bars=180),
    EIGHT.variant("8R + 10% cap + 250 bars", max_position_pct=0.10, max_hold_bars=250),
    # A wider target, now that positions are smaller.
    EIGHT.variant("10R + 10% cap + 180 bars", target_r=10.0,
                  max_position_pct=0.10, max_hold_bars=180),
]


def window(label, lo, hi):
    uni = {s: f.loc[lo:hi] for s, f in frames.items()}
    bm = {t: f.loc[lo:hi] for t, f in benchmarks.items()}
    print(f"\n{'=' * 92}\n{label}\n{'=' * 92}")
    print(f"  {'variant':<28}{'trades':>7}{'win%':>7}{'end $':>12}"
          f"{'cagr%':>8}{'maxDD%':>8}{'sharpe':>8}")
    rows = []
    for cfg in ARMS:
        perf, curve, _ = run_config(cfg, uni, bm, starting_equity=START)
        print(f"  {cfg.name:<28}{perf.trades:>7}{perf.win_rate * 100:>7.1f}"
              f"{float(curve.iloc[-1]):>12,.0f}{perf.cagr * 100:>8.1f}"
              f"{perf.max_drawdown * 100:>8.1f}{perf.sharpe:>8.2f}", flush=True)
        rows.append({"window": label, "variant": cfg.name, "trades": perf.trades,
                     "win%": round(perf.win_rate * 100, 1),
                     "end_$": round(float(curve.iloc[-1])),
                     "cagr%": round(perf.cagr * 100, 1),
                     "maxDD%": round(perf.max_drawdown * 100, 1),
                     "sharpe": round(perf.sharpe, 2)})
    spy = bm["SPY"]["close"] / bm["SPY"]["close"].iloc[0]
    print(f"  {'SPY buy & hold':<28}{'-':>7}{'-':>7}{START * float(spy.iloc[-1]):>12,.0f}"
          f"{metrics.cagr(spy) * 100:>8.1f}{metrics.max_drawdown(spy) * 100:>8.1f}"
          f"{metrics.sharpe(spy):>8.2f}")
    return rows


rows = []
rows += window("OUT-OF-SAMPLE   2006-01-03 to 2020-12-31", None, "2020-12-31")
rows += window("TUNING WINDOW   2021-01-04 to 2026-09-09", "2021-01-01", None)
rows += window("FULL 20 YEARS   2006-01-03 to 2026-09-09", None, None)
pd.DataFrame(rows).to_csv("results_refined.csv", index=False)
print("\nwrote results_refined.csv")
