"""Same grid as the walk-forward, run on the last five years.

Identical candidate set to the 2011-2026 comparison so the two tables can be
read against each other, plus the risk-size variants. Reported on one path and
then re-checked across opening balances, because which signals become trades
depends on cash and a single path overstates precision.
"""

from __future__ import annotations

import itertools
import numpy as np
import pandas as pd

import data as data_mod
import metrics
from backtester import Backtester
from strategy import StrategyConfig, prepare_symbol

LO = "2021-09-11"
frames = data_mod.load_csv_dir("bars")
benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ")}
uni = {s: f.loc[LO:] for s, f in frames.items()}
bm = {t: f.loc[LO:] for t, f in benchmarks.items()}
cal = bm["SPY"].index
years = (cal[-1] - cal[0]).days / 365.25
print(f"{cal[0].date()} -> {cal[-1].date()}   {len(cal)} sessions, {years:.2f} years\n")

GRID = [StrategyConfig(name=f"{t:g}R / {'gap' if g=='required' else 'no gap'} / {s:g}xATR",
                       target_r=t, gap_mode=g, atr_stop_mult=s,
                       max_hold_bars=250, risk_pct=0.010, max_open_positions=15)
        for t, g, s in itertools.product((4.0, 8.0, 12.0), ("ignored", "required"), (1.5, 2.0))]
BEST_SHAPE = dict(target_r=8.0, gap_mode="ignored", atr_stop_mult=1.5,
                  max_hold_bars=250, max_open_positions=15)
GRID += [StrategyConfig(name=f"8R / no gap / 1.5xATR @ {r:.2%} risk", risk_pct=r, **BEST_SHAPE)
         for r in (0.005, 0.015, 0.020)]

# Indicators do not depend on target_r or risk_pct.
PREP = {}
for cfg in GRID:
    k = (cfg.atr_stop_mult, cfg.gap_mode)
    if k not in PREP:
        PREP[k] = {s: prepare_symbol(f, cfg) for s, f in uni.items()}

rows = []
for cfg in GRID:
    eng = Backtester(cfg, starting_equity=100_000.0)
    curve, blot = eng.run(uni, bm, prepared=PREP[(cfg.atr_stop_mult, cfg.gap_mode)])
    p = metrics.summarise(curve, blot, exposure=eng.exposure)
    rows.append({"strategy": cfg.name, "ending_$": round(float(curve.iloc[-1])),
                 "profit_$": round(float(curve.iloc[-1]) - 100_000),
                 "cagr%": round(p.cagr*100, 1), "maxDD%": round(p.max_drawdown*100, 1),
                 "worstloss_$": round(100_000*p.max_drawdown),
                 "sharpe": round(p.sharpe, 2), "MAR": round(p.cagr/p.max_drawdown, 2),
                 "trades": p.trades, "win%": round(p.win_rate*100, 1),
                 "PF": round(p.profit_factor, 2)})
    print(f"  {cfg.name:<34}${float(curve.iloc[-1]):>10,.0f}  {p.cagr*100:>5.1f}% cagr  "
          f"{p.max_drawdown*100:>5.1f}% DD  {p.sharpe:.2f}", flush=True)

t = pd.DataFrame(rows).sort_values("ending_$", ascending=False)
t.to_csv("grid_5y.csv", index=False)
print("\n" + "=" * 104)
print("FIVE YEARS, RANKED BY RETURN")
print("=" * 104)
print(t.to_string(index=False))

for lab, fr in (("SPY", bm["SPY"]), ("QQQ", bm["QQQ"])):
    c = fr["close"]/fr["close"].iloc[0]
    print(f"\n  {lab} buy & hold: ${100_000*float(c.iloc[-1]):,.0f}   "
          f"{metrics.cagr(c)*100:.1f}% cagr   {metrics.max_drawdown(c)*100:.1f}% maxDD   "
          f"sharpe {metrics.sharpe(c):.2f}")

# --- winner detail + path robustness --------------------------------------
win = next(c for c in GRID if c.name == t.iloc[0]["strategy"])
print("\n" + "=" * 104)
print(f"WINNER: {win.name}".center(104))
print("=" * 104)
eng = Backtester(win, starting_equity=100_000.0)
curve, blot = eng.run(uni, bm, prepared=PREP[(win.atr_stop_mult, win.gap_mode)])
p = metrics.summarise(curve, blot, exposure=eng.exposure)
w, l = blot[blot.pnl > 0], blot[blot.pnl <= 0]
peak = curve.cummax(); dd = 1-curve/peak; tr = dd.idxmax(); top = curve.loc[:tr].idxmax()
rec = curve.loc[tr:][curve.loc[tr:] >= curve.loc[top]]
print(f"  ${100_000:,} -> ${float(curve.iloc[-1]):,.0f}  (profit ${float(curve.iloc[-1])-100_000:,.0f})")
print(f"  worst drawdown {p.max_drawdown:.1%}: ${curve.loc[top]:,.0f} {top.date()} -> "
      f"${curve.loc[tr]:,.0f} {tr.date()}, back in "
      f"{(rec.index[0]-top).days//30 if len(rec) else 'n/a'} months")
print(f"  {p.trades} trades | {len(w)} wins ({p.win_rate:.1%}) | PF {p.profit_factor:.2f} "
      f"| avg win ${w.pnl.mean():,.0f} vs avg loss ${l.pnl.mean():,.0f}")
print("\n  year by year:")
yr = metrics.yearly_returns(curve); eoy = curve.resample("YE").last(); prev = 100_000.0
spyyr = metrics.yearly_returns(bm["SPY"]["close"]/bm["SPY"]["close"].iloc[0])
for y in yr.index:
    bal = float(eoy[eoy.index.year == y].iloc[0])
    print(f"    {y}  {yr[y]*100:>7.1f}%   profit ${bal-prev:>10,.0f}   balance ${bal:>10,.0f}"
          f"   SPY {spyyr.get(y, float('nan'))*100:>6.1f}%")
    prev = bal
sym = blot.groupby("symbol").pnl.sum().sort_values(ascending=False)
print(f"\n  top earners: " + ", ".join(f"{s} ${v:,.0f}" for s, v in sym.head(6).items()))
print(f"  worst:       " + ", ".join(f"{s} ${v:,.0f}" for s, v in sym.tail(4).items()))

print("\n  robustness across opening balances (normalised to $100k):")
vals = []
for eq in (94_000, 97_000, 100_000, 103_000, 106_000, 110_000):
    e2 = Backtester(win, starting_equity=float(eq))
    c2, _ = e2.run(uni, bm, prepared=PREP[(win.atr_stop_mult, win.gap_mode)])
    v = float(c2.iloc[-1])/eq*100_000
    vals.append(v)
    print(f"    start ${eq:>7,} -> ${v:>10,.0f}")
s = pd.Series(vals)
print(f"    median ${s.median():,.0f}   range ${s.min():,.0f}-${s.max():,.0f}   "
      f"spread {s.max()/s.min():.2f}x")
