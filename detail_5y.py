"""Five-year detail for the preset that actually ships (`balanced`)."""
from __future__ import annotations
import pandas as pd
import data as data_mod, metrics
from backtester import run_config
from strategy import preset

LO, START = "2021-09-11", 100_000.0
frames = data_mod.load_csv_dir("bars")
bm = {t: frames.pop(t).loc[LO:] for t in ("SPY", "QQQ")}
uni = {s: f.loc[LO:] for s, f in frames.items()}
cfg = preset("balanced")
perf, curve, blot = run_config(cfg, uni, bm, starting_equity=START)
end = float(curve.iloc[-1]); cal = bm["SPY"].index

print("=" * 84)
print(f"'{cfg.name}'  |  {cal[0].date()} -> {cal[-1].date()}  "
      f"({(cal[-1]-cal[0]).days/365.25:.2f} years)")
print("=" * 84)
print(f"  8R target | no gap filter | {cfg.atr_stop_mult:g}xATR stop | "
      f"{cfg.risk_pct:.1%} risk | {cfg.max_hold_bars} bars | {cfg.max_open_positions} slots\n")
print(f"  START        ${START:>12,.0f}")
print(f"  END          ${end:>12,.0f}")
print(f"  PROFIT       ${end-START:>12,.0f}   ({perf.total_return:.1%})")
print(f"  CAGR         {perf.cagr:>13.2%}")
print(f"  max drawdown {perf.max_drawdown:>13.1%}   (${START*perf.max_drawdown:,.0f} on $100k)")
print(f"  sharpe       {perf.sharpe:>13.2f}      MAR {perf.cagr/perf.max_drawdown:.2f}")

peak = curve.cummax(); dd = 1-curve/peak; tr = dd.idxmax(); top = curve.loc[:tr].idxmax()
rec = curve.loc[tr:][curve.loc[tr:] >= curve.loc[top]]
print(f"\n  worst stretch: ${curve.loc[top]:,.0f} ({top.date()}) -> "
      f"${curve.loc[tr]:,.0f} ({tr.date()}), back in "
      f"{(rec.index[0]-top).days//30 if len(rec) else 'n/a'} months")

w, l = blot[blot.pnl>0], blot[blot.pnl<=0]
print(f"\n  {perf.trades} trades | {len(w)} wins ({perf.win_rate:.1%}) | "
      f"PF {perf.profit_factor:.2f} | expectancy ${blot.pnl.mean():,.0f} ({perf.expectancy_r:+.2f}R)")
print(f"  avg win ${w.pnl.mean():,.0f} ({w.r_multiple.mean():+.2f}R)   "
      f"avg loss ${l.pnl.mean():,.0f} ({l.r_multiple.mean():+.2f}R)")
print(f"  biggest win ${blot.pnl.max():,.0f}   biggest loss ${blot.pnl.min():,.0f}")
print("\n  exits: " + " | ".join(
    f"{r} {n} (${blot[blot.exit_reason==r].pnl.sum():,.0f})"
    for r, n in blot.exit_reason.value_counts().items()))

print("\n  year by year:")
yr = metrics.yearly_returns(curve); eoy = curve.resample("YE").last(); prev = START
spyyr = metrics.yearly_returns(bm["SPY"]["close"]/bm["SPY"]["close"].iloc[0])
print(f"    {'year':<6}{'trades':>7}{'return':>9}{'profit':>12}{'balance':>13}{'SPY':>8}")
for y in yr.index:
    bal = float(eoy[eoy.index.year==y].iloc[0]); n = int((blot.entry_date.dt.year==y).sum())
    print(f"    {y:<6}{n:>7}{yr[y]*100:>8.1f}%{bal-prev:>12,.0f}{bal:>13,.0f}"
          f"{spyyr.get(y,float('nan'))*100:>7.1f}%")
    prev = bal

sym = blot.groupby("symbol").agg(n=("pnl","size"), pnl=("pnl","sum")).sort_values("pnl", ascending=False)
print("\n  top earners:  " + ", ".join(f"{s} ${v.pnl:,.0f}" for s, v in sym.head(6).iterrows()))
print("  worst:        " + ", ".join(f"{s} ${v.pnl:,.0f}" for s, v in sym.tail(4).iterrows()))
print(f"  profitable names: {(sym.pnl>0).sum()} of {len(sym)}   |   "
      f"top 5 = {sym.head(5).pnl.sum()/blot.pnl.sum():.0%} of profit")

print("\n  benchmarks over the same window:")
for lab, fr in (("SPY", bm["SPY"]), ("QQQ", bm["QQQ"])):
    c = fr["close"]/fr["close"].iloc[0]
    print(f"    {lab}: ${START*float(c.iloc[-1]):>10,.0f}   {metrics.cagr(c)*100:>5.1f}% cagr   "
          f"{metrics.max_drawdown(c)*100:>5.1f}% maxDD   sharpe {metrics.sharpe(c):.2f}")

print("\n  same preset across opening balances (normalised to $100k):")
vals = []
for eq in (94_000, 97_000, 100_000, 103_000, 106_000, 110_000):
    _, c2, _ = run_config(cfg, uni, bm, starting_equity=float(eq))
    vals.append(float(c2.iloc[-1])/eq*START)
s = pd.Series(vals)
print(f"    median ${s.median():,.0f}   range ${s.min():,.0f} - ${s.max():,.0f}   "
      f"spread {s.max()/s.min():.2f}x")
