"""How much money can this make, and what does the extra cost?

Raising risk per trade previously looked harmful. That was the cash defect
deleting up to 97% of entries rather than sizing them down. With that repaired,
the size dial can be measured honestly for the first time.

Position size is the only lever here that is not a parameter fitted to this
data. Sweeping targets and hold limits until the number peaks is how a backtest
gets rich and an account does not.
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

BEST = StrategyConfig(name="8R + 250 bars", target_r=8.0, max_hold_bars=250)

ARMS = [
    BEST.variant("risk 0.50%", risk_pct=0.005),
    BEST.variant("risk 0.75%", risk_pct=0.0075),
    BEST.variant("risk 1.00%", risk_pct=0.010),
    BEST.variant("risk 1.50%", risk_pct=0.015),
    BEST.variant("risk 2.00%", risk_pct=0.020),
    BEST.variant("risk 1.00%, 15 slots", risk_pct=0.010, max_open_positions=15),
    BEST.variant("risk 1.00%, 20 slots", risk_pct=0.010, max_open_positions=20),
]


def window(label, lo, hi):
    uni = {s: f.loc[lo:hi] for s, f in frames.items()}
    bm = {t: f.loc[lo:hi] for t, f in benchmarks.items()}
    print(f"\n{'=' * 100}\n{label}\n{'=' * 100}")
    print(f"  {'variant':<24}{'trades':>7}{'win%':>7}{'end $':>13}{'cagr%':>8}"
          f"{'maxDD%':>8}{'worst $':>11}{'sharpe':>8}{'MAR':>7}")
    rows = []
    for cfg in ARMS:
        perf, curve, _ = run_config(cfg, uni, bm, starting_equity=START)
        mar = perf.cagr / perf.max_drawdown if perf.max_drawdown else float("nan")
        print(f"  {cfg.name:<24}{perf.trades:>7}{perf.win_rate * 100:>7.1f}"
              f"{float(curve.iloc[-1]):>13,.0f}{perf.cagr * 100:>8.1f}"
              f"{perf.max_drawdown * 100:>8.1f}{START * perf.max_drawdown:>11,.0f}"
              f"{perf.sharpe:>8.2f}{mar:>7.2f}", flush=True)
        rows.append({"window": label, "variant": cfg.name, "trades": perf.trades,
                     "end_$": round(float(curve.iloc[-1])),
                     "cagr%": round(perf.cagr * 100, 1),
                     "maxDD%": round(perf.max_drawdown * 100, 1),
                     "sharpe": round(perf.sharpe, 2), "MAR": round(mar, 2)})
    spy = bm["SPY"]["close"] / bm["SPY"]["close"].iloc[0]
    dd = metrics.max_drawdown(spy)
    print(f"  {'SPY buy & hold':<24}{'-':>7}{'-':>7}{START * float(spy.iloc[-1]):>13,.0f}"
          f"{metrics.cagr(spy) * 100:>8.1f}{dd * 100:>8.1f}{START * dd:>11,.0f}"
          f"{metrics.sharpe(spy):>8.2f}{metrics.cagr(spy) / dd:>7.2f}")
    return rows


rows = []
rows += window("OUT-OF-SAMPLE   2006-01-03 to 2020-12-31", None, "2020-12-31")
rows += window("FULL 20 YEARS   2006-01-03 to 2026-09-09", None, None)
pd.DataFrame(rows).to_csv("results_maximise.csv", index=False)

# --- The worst stretch, in dollars, for the arm that made the most ----------
print("\n" + "=" * 100)
print("WHAT THE BIGGEST ARM ACTUALLY PUT YOU THROUGH (full 20 years)")
print("=" * 100)
for cfg in (ARMS[0], ARMS[3], ARMS[4]):
    perf, curve, blot = run_config(cfg, frames, benchmarks, starting_equity=START)
    peak = curve.cummax()
    dd = 1 - curve / peak
    trough = dd.idxmax()
    start = curve.loc[:trough].idxmax()
    recovered = curve.loc[trough:][curve.loc[trough:] >= curve.loc[start]]
    back = recovered.index[0] if len(recovered) else None
    print(f"\n  {cfg.name}: ended ${float(curve.iloc[-1]):,.0f}")
    print(f"    worst drawdown {dd.max():.1%} - ${curve.loc[start]:,.0f} on "
          f"{start.date()} down to ${curve.loc[trough]:,.0f} on {trough.date()}")
    print(f"    time to recover: "
          + (f"{(back - start).days // 30} months (back on {back.date()})" if back
             else "never recovered within the test"))
    yearly = metrics.yearly_returns(curve)
    print(f"    losing years: {(yearly < 0).sum()} of {len(yearly)}"
          f"  |  worst year {yearly.min():.1%}  |  best year {yearly.max():.1%}")
