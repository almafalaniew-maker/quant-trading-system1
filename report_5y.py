"""Five-year results: 2021-09-11 to 2026-09-11.

Reported as a distribution rather than a single run. Which signals become trades
depends on cash and slot availability, so one backtest is one path - nudging the
opening balance reshuffles which winners get caught without changing the edge.
Each candidate is run across nine opening balances and ranked on the median.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import data as data_mod
import metrics
from backtester import run_config
from strategy import StrategyConfig

LO = "2021-09-11"
STARTS = [94_000, 96_000, 98_000, 100_000, 102_000, 104_000, 106_000, 108_000, 110_000]

frames = data_mod.load_csv_dir("bars")
benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ")}
uni = {s: f.loc[LO:] for s, f in frames.items()}
bm = {t: f.loc[LO:] for t, f in benchmarks.items()}
cal = bm["SPY"].index
print(f"window {cal[0].date()} -> {cal[-1].date()}  ({len(cal)} sessions, "
      f"{(cal[-1] - cal[0]).days / 365.25:.1f} years)\n")

BASE = StrategyConfig(name="8R/250/1.0%/15", target_r=8.0, max_hold_bars=250,
                      risk_pct=0.010, max_open_positions=15)
CANDIDATES = [
    BASE,
    BASE.variant("+ gap >=2.5%", gap_mode="required"),
    BASE.variant("+ 1.5xATR stop", atr_stop_mult=1.5),
    BASE.variant("+ gap + 1.5xATR", gap_mode="required", atr_stop_mult=1.5),
    BASE.variant("risk 1.5%", risk_pct=0.015),
    BASE.variant("risk 0.5%", risk_pct=0.005),
    BASE.variant("target 4R", target_r=4.0),
]

print("=" * 104)
print("FIVE-YEAR RESULT ACROSS 9 OPENING BALANCES (normalised to $100,000)")
print("=" * 104)
print(f"  {'candidate':<22}{'median $':>11}{'worst':>11}{'best':>11}{'spread':>9}"
      f"{'cagr':>8}{'maxDD':>8}{'sharpe':>8}{'trades':>8}{'win%':>7}")
rows = []
for cfg in CANDIDATES:
    ends, cagrs, dds, shs, tr, wr = [], [], [], [], [], []
    for eq in STARTS:
        perf, curve, blot = run_config(cfg, uni, bm, starting_equity=float(eq))
        ends.append(float(curve.iloc[-1]) / eq * 100_000.0)
        cagrs.append(perf.cagr); dds.append(perf.max_drawdown)
        shs.append(perf.sharpe); tr.append(perf.trades); wr.append(perf.win_rate)
    e = pd.Series(ends)
    print(f"  {cfg.name:<22}{e.median():>11,.0f}{e.min():>11,.0f}{e.max():>11,.0f}"
          f"{e.max()/e.min():>8.2f}x{np.median(cagrs)*100:>7.1f}%"
          f"{np.median(dds)*100:>7.1f}%{np.median(shs):>8.2f}"
          f"{int(np.median(tr)):>8}{np.median(wr)*100:>6.1f}%", flush=True)
    rows.append({"candidate": cfg.name, "median_$": round(e.median()),
                 "worst_$": round(e.min()), "best_$": round(e.max()),
                 "spread_x": round(e.max()/e.min(), 2),
                 "cagr%": round(np.median(cagrs)*100, 1),
                 "maxDD%": round(np.median(dds)*100, 1),
                 "sharpe": round(np.median(shs), 2),
                 "trades": int(np.median(tr))})

table = pd.DataFrame(rows).sort_values("median_$", ascending=False)
table.to_csv("results_5y.csv", index=False)

for label, series in (("SPY", bm["SPY"]), ("QQQ", bm["QQQ"])):
    c = series["close"] / series["close"].iloc[0]
    print(f"  {label + ' buy & hold':<22}{100_000*float(c.iloc[-1]):>11,.0f}"
          f"{'-':>11}{'-':>11}{'-':>9}{metrics.cagr(c)*100:>7.1f}%"
          f"{metrics.max_drawdown(c)*100:>7.1f}%{metrics.sharpe(c):>8.2f}")
ew = pd.concat([(f["close"]/f["close"].iloc[0]).reindex(cal).ffill()
                for f in uni.values() if len(f) > 1], axis=1).mean(axis=1)
print(f"  {'equal-weight hold':<22}{100_000*float(ew.iloc[-1]):>11,.0f}{'-':>11}{'-':>11}"
      f"{'-':>9}{metrics.cagr(ew)*100:>7.1f}%{metrics.max_drawdown(ew)*100:>7.1f}%"
      f"{metrics.sharpe(ew):>8.2f}")

print("\n" + "=" * 104)
print("RANKED BY MEDIAN")
print("=" * 104)
print(table.to_string(index=False))

# --- Full detail on the median-best candidate ------------------------------
best_name = table.iloc[0]["candidate"]
BEST = next(c for c in CANDIDATES if c.name == best_name)
perf, curve, blot = run_config(BEST, uni, bm, starting_equity=100_000.0)
end = float(curve.iloc[-1])

print("\n" + "=" * 104)
print(f"DETAIL: {best_name}".center(104))
print("=" * 104)
print(f"  start $100,000  ->  end ${end:,.0f}   profit ${end - 100_000:,.0f}"
      f"   ({perf.total_return:.1%} total, {perf.cagr:.2%} a year)")
peak = curve.cummax(); dd = 1 - curve/peak
tr = dd.idxmax(); top = curve.loc[:tr].idxmax()
rec = curve.loc[tr:][curve.loc[tr:] >= curve.loc[top]]
print(f"  worst drawdown {perf.max_drawdown:.1%}: ${curve.loc[top]:,.0f} ({top.date()})"
      f" -> ${curve.loc[tr]:,.0f} ({tr.date()})")
print(f"  underwater {(rec.index[0]-top).days//30 if len(rec) else 0} months"
      f"   sharpe {perf.sharpe:.2f}   MAR {perf.cagr/perf.max_drawdown:.2f}")
w, l = blot[blot.pnl > 0], blot[blot.pnl <= 0]
print(f"\n  {len(blot)} trades: {len(w)} wins ({len(w)/len(blot):.1%}), {len(l)} losses")
print(f"  avg win ${w.pnl.mean():,.0f} ({w.r_multiple.mean():+.2f}R)   "
      f"avg loss ${l.pnl.mean():,.0f} ({l.r_multiple.mean():+.2f}R)")
print(f"  profit factor {perf.profit_factor:.2f}   expectancy ${blot.pnl.mean():,.0f} "
      f"({perf.expectancy_r:+.3f}R)")
print(f"  biggest win ${blot.pnl.max():,.0f}   biggest loss ${blot.pnl.min():,.0f}")
print("\n  exits:")
for r, n in blot.exit_reason.value_counts().items():
    sub = blot[blot.exit_reason == r]
    print(f"    {r:<13}{n:>4} ({n/len(blot):>5.1%})  ${sub.pnl.sum():>11,.0f}  "
          f"{sub.r_multiple.mean():+.2f}R avg")

print("\n  year by year:")
yr = metrics.yearly_returns(curve); eoy = curve.resample("YE").last()
spy_c = bm["SPY"]["close"]/bm["SPY"]["close"].iloc[0]
spy_yr = metrics.yearly_returns(spy_c)
prev = 100_000.0
print(f"    {'year':<7}{'trades':>7}{'return':>9}{'profit $':>12}{'balance $':>13}{'SPY':>9}")
for y in yr.index:
    bal = float(eoy[eoy.index.year == y].iloc[0])
    n = int((blot.entry_date.dt.year == y).sum())
    print(f"    {y:<7}{n:>7}{yr[y]*100:>8.1f}%{bal-prev:>12,.0f}{bal:>13,.0f}"
          f"{spy_yr.get(y, float('nan'))*100:>8.1f}%")
    prev = bal

sym = (blot.groupby("symbol").agg(trades=("pnl","size"), profit=("pnl","sum"),
       win=("r_multiple", lambda s:(s>0).mean())).sort_values("profit", ascending=False))
print(f"\n  top 10 earners:")
for s, r in sym.head(10).iterrows():
    print(f"    {s:<7}{int(r.trades):>3} trades  ${r.profit:>10,.0f}  {r.win*100:>3.0f}% win")
print(f"  worst 5:")
for s, r in sym.tail(5).iterrows():
    print(f"    {s:<7}{int(r.trades):>3} trades  ${r.profit:>10,.0f}  {r.win*100:>3.0f}% win")
print(f"\n  profitable names {(sym.profit>0).sum()} of {len(sym)}   |   "
      f"top 5 = ${sym.head(5).profit.sum():,.0f} ({sym.head(5).profit.sum()/blot.pnl.sum():.0%} of profit)")
blot.to_csv("trades_5y.csv", index=False)
