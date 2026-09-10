"""Why did the strategy trail buy-and-hold on the same names?

Three candidate explanations, each measurable:
  1. It is barely invested - risk-based sizing with a tight stop buys very little.
  2. The 4R target caps the winners in a market whose winners went far past 4R.
  3. The regime gate sits it out during recoveries.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import data as data_mod
from backtester import Backtester, run_config
from strategy import StrategyConfig, prepare_symbol, regime_series

frames = data_mod.load_csv_dir("bars")
benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ")}
cfg = StrategyConfig(name="baseline_fixed_4R")

# --- 1. How much capital is actually at work? ------------------------------
prepared = {s: prepare_symbol(f, cfg) for s, f in frames.items()}
engine = Backtester(cfg)
curve, blotter = engine.run(frames, benchmarks)

cash = engine.starting_equity
deployed, counts = [], []
open_pos: dict = {}
for date in benchmarks["SPY"].index:
    pass  # exposure is recomputed below from the blotter, which is simpler

# Reconstruct daily invested notional from the blotter.
notional = pd.Series(0.0, index=benchmarks["SPY"].index)
held = pd.Series(0, index=benchmarks["SPY"].index)
for _, t in blotter.iterrows():
    window = notional.loc[t["entry_date"]:t["exit_date"]].index
    px = prepared[t["symbol"]].loc[window, "close"]
    notional.loc[window] += px * t["shares"]
    held.loc[window] += 1

exposure = (notional / curve).clip(upper=5)
print("=" * 76)
print("1. HOW MUCH CAPITAL WAS AT WORK")
print("=" * 76)
print(f"  mean invested notional      {exposure.mean():>7.1%} of equity")
print(f"  median                      {exposure.median():>7.1%}")
print(f"  90th percentile             {exposure.quantile(0.9):>7.1%}")
print(f"  days fully flat             {(held == 0).mean():>7.1%}")
print(f"  mean positions held         {held.mean():>7.2f} of {cfg.max_open_positions}")
print("\n  Buy-and-hold runs at 100% the whole time. Sizing by a 0.5% risk budget")
print("  against a ~2xATR stop buys far less than the account can carry.")

# --- 2. What did the 4R cap cost? ------------------------------------------
print("\n" + "=" * 76)
print("2. WHAT THE 4R TARGET COST")
print("=" * 76)

mfe = []
for _, t in blotter.iterrows():
    frame = prepared[t["symbol"]]
    fwd = frame.loc[t["entry_date"]:].iloc[1:121]
    if fwd.empty:
        continue
    peak = (fwd["high"].max() - t["entry_price"]) / t["risk_per_share"]
    mfe.append({"realised_r": t["r_multiple"], "peak_r": peak,
                "reason": t["exit_reason"]})
mfe = pd.DataFrame(mfe)
winners = mfe[mfe["reason"] == "target"]
print(f"  trades exiting at the 4R target: {len(winners)}")
print(f"  of those, the median went on to {winners['peak_r'].median():.1f}R within 120 days")
print(f"  and the top decile to           {winners['peak_r'].quantile(0.9):.1f}R")
print(f"  total R left on the table by capping at 4R: "
      f"{(winners['peak_r'] - 4).clip(lower=0).sum():,.0f}R")

# --- 3. Would letting winners run fix it? ----------------------------------
print("\n" + "=" * 76)
print("3. RAISING OR REMOVING THE CAP")
print("=" * 76)
print(f"  {'variant':<34}{'trades':>7}{'win%':>7}{'ret%':>9}{'cagr%':>8}{'maxDD%':>8}{'sharpe':>8}")
variants = [
    cfg,
    cfg.variant("target 6R", target_r=6.0),
    cfg.variant("target 8R", target_r=8.0),
    cfg.variant("target 12R", target_r=12.0),
    cfg.variant("no target, trail 3xATR", exit_mode="scale_out",
                scale_fraction=0.0, trail_atr_mult=3.0),
    cfg.variant("no target, trail 5xATR", exit_mode="scale_out",
                scale_fraction=0.0, trail_atr_mult=5.0),
]
for v in variants:
    perf, _, _ = run_config(v, frames, benchmarks)
    print(f"  {v.name:<34}{perf.trades:>7}{perf.win_rate * 100:>7.1f}"
          f"{perf.total_return * 100:>9.1f}{perf.cagr * 100:>8.1f}"
          f"{perf.max_drawdown * 100:>8.1f}{perf.sharpe:>8.2f}")

# --- 4. What does more capital at work do? ---------------------------------
print("\n" + "=" * 76)
print("4. PUTTING MORE CAPITAL TO WORK")
print("=" * 76)
print(f"  {'variant':<34}{'trades':>7}{'win%':>7}{'ret%':>9}{'cagr%':>8}{'maxDD%':>8}{'sharpe':>8}")
for v in [
    cfg,
    cfg.variant("risk 1.0%", risk_pct=0.010),
    cfg.variant("risk 1.5%", risk_pct=0.015),
    cfg.variant("risk 1.0%, 20 slots", risk_pct=0.010, max_open_positions=20),
    cfg.variant("risk 1.5%, 20 slots", risk_pct=0.015, max_open_positions=20),
]:
    perf, _, _ = run_config(v, frames, benchmarks)
    print(f"  {v.name:<34}{perf.trades:>7}{perf.win_rate * 100:>7.1f}"
          f"{perf.total_return * 100:>9.1f}{perf.cagr * 100:>8.1f}"
          f"{perf.max_drawdown * 100:>8.1f}{perf.sharpe:>8.2f}")
