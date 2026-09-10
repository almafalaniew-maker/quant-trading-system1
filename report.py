"""Full account report for the best configuration found.

Config: 8R target, 250-bar hold, 1.0% risk per trade, 15 concurrent slots.
Chosen because it won out-of-sample (2006-2020) as well as over the full period,
not because it topped a single sweep.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import data as data_mod
import metrics
from backtester import run_config
from strategy import StrategyConfig

START = 100_000.0
pd.set_option("display.width", 200)

frames = data_mod.load_csv_dir("bars")
benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ")}

BEST = StrategyConfig(name="8R / 250 bars / 1.0% risk / 15 slots",
                      target_r=8.0, max_hold_bars=250,
                      risk_pct=0.010, max_open_positions=15)

perf, curve, blot = run_config(BEST, frames, benchmarks, starting_equity=START)
end = float(curve.iloc[-1])

def money(x): return f"${x:,.0f}"

print("=" * 92)
print("ACCOUNT SUMMARY".center(92))
print("=" * 92)
print(f"  configuration        {BEST.name}")
print(f"  period               {curve.index[0].date()} to {curve.index[-1].date()}"
      f"   ({(curve.index[-1] - curve.index[0]).days / 365.25:.1f} years)")
print(f"  universe             {len(frames)} equities, regime gated on SPY")
print()
print(f"  starting capital     {money(START)}")
print(f"  ending capital       {money(end)}")
print(f"  PROFIT               {money(end - START)}")
print(f"  total return         {perf.total_return:.1%}")
print(f"  compound annual      {perf.cagr:.2%}")
print(f"  multiple on capital  {end / START:.1f}x")

print("\n" + "=" * 92)
print("RISK".center(92))
print("=" * 92)
peak = curve.cummax()
dd = 1 - curve / peak
trough = dd.idxmax(); top = curve.loc[:trough].idxmax()
rec = curve.loc[trough:][curve.loc[trough:] >= curve.loc[top]]
print(f"  worst drawdown       {perf.max_drawdown:.1%}")
print(f"    from               {money(curve.loc[top])} on {top.date()}")
print(f"    down to            {money(curve.loc[trough])} on {trough.date()}")
print(f"    dollars lost       {money(curve.loc[top] - curve.loc[trough])}")
print(f"    recovered          {rec.index[0].date() if len(rec) else 'not within test'}"
      f"  ({(rec.index[0] - top).days // 30 if len(rec) else 0} months underwater)")
print(f"  sharpe ratio         {perf.sharpe:.2f}")
print(f"  MAR (cagr/maxDD)     {perf.cagr / perf.max_drawdown:.2f}")
print(f"  time in the market   {perf.exposure:.0%} of days")

print("\n" + "=" * 92)
print("TRADES".center(92))
print("=" * 92)
wins, losses = blot[blot["pnl"] > 0], blot[blot["pnl"] <= 0]
print(f"  total trades         {len(blot):,}")
print(f"  winners              {len(wins):,} ({len(wins)/len(blot):.1%})")
print(f"  losers               {len(losses):,} ({len(losses)/len(blot):.1%})")
print(f"  gross profit         {money(wins['pnl'].sum())}")
print(f"  gross loss           {money(losses['pnl'].sum())}")
print(f"  profit factor        {perf.profit_factor:.2f}")
print()
print(f"  average win          {money(wins['pnl'].mean())}   ({wins['r_multiple'].mean():+.2f}R)")
print(f"  average loss         {money(losses['pnl'].mean())}   ({losses['r_multiple'].mean():+.2f}R)")
print(f"  expectancy per trade {money(blot['pnl'].mean())}   ({perf.expectancy_r:+.3f}R)")
print(f"  largest win          {money(blot['pnl'].max())}   ({blot['r_multiple'].max():+.2f}R)")
print(f"  largest loss         {money(blot['pnl'].min())}   ({blot['r_multiple'].min():+.2f}R)")
print(f"  win/loss size ratio  {abs(wins['pnl'].mean() / losses['pnl'].mean()):.2f}x")

streak = (blot.sort_values("exit_date")["pnl"] > 0).astype(int)
groups = (streak != streak.shift()).cumsum()
runs = streak.groupby(groups).agg(["first", "size"])
print(f"  longest win streak   {runs[runs['first'] == 1]['size'].max()}")
print(f"  longest lose streak  {runs[runs['first'] == 0]['size'].max()}")

print("\n  how trades ended:")
for reason, n in blot["exit_reason"].value_counts().items():
    sub = blot[blot["exit_reason"] == reason]
    print(f"    {reason:<14}{n:>5} ({n/len(blot):>5.1%})   "
          f"{money(sub['pnl'].sum()):>12} total   {sub['r_multiple'].mean():+.2f}R avg")

print("\n" + "=" * 92)
print("YEAR BY YEAR".center(92))
print("=" * 92)
yr = metrics.yearly_returns(curve)
eoy = curve.resample("YE").last()
spy_c = benchmarks["SPY"]["close"] / benchmarks["SPY"]["close"].iloc[0]
spy_yr = metrics.yearly_returns(spy_c)
rows = []
prev = START
for year in yr.index:
    bal = float(eoy[eoy.index.year == year].iloc[0])
    n = int((blot["entry_date"].dt.year == year).sum())
    rows.append({"year": year, "trades": n, "return%": round(yr[year] * 100, 1),
                 "profit_$": round(bal - prev), "balance_$": round(bal),
                 "SPY%": round(spy_yr.get(year, np.nan) * 100, 1)})
    prev = bal
ytab = pd.DataFrame(rows)
print(ytab.to_string(index=False))
print(f"\n  winning years {(ytab['return%'] > 0).sum()} of {len(ytab)}"
      f"   |   beat SPY in {(ytab['return%'] > ytab['SPY%']).sum()} of {len(ytab)}")
print(f"  best {ytab['return%'].max():.1f}%   worst {ytab['return%'].min():.1f}%")

print("\n" + "=" * 92)
print("BY SYMBOL".center(92))
print("=" * 92)
sym = (blot.groupby("symbol")
       .agg(trades=("pnl", "size"), profit=("pnl", "sum"),
            win_rate=("r_multiple", lambda s: (s > 0).mean()),
            best_R=("r_multiple", "max"))
       .sort_values("profit", ascending=False))
sym["profit"] = sym["profit"].round(0)
sym["win_rate"] = (sym["win_rate"] * 100).round(0)
print("\n  TOP 15 EARNERS")
print(sym.head(15).to_string())
print("\n  15 WORST")
print(sym.tail(15).to_string())
print(f"\n  profitable names {(sym['profit'] > 0).sum()} of {len(sym)}")
print(f"  top 5 names       {money(sym.head(5)['profit'].sum())} "
      f"({sym.head(5)['profit'].sum() / blot['pnl'].sum():.0%} of all profit)")
print(f"  top 10 names      {money(sym.head(10)['profit'].sum())} "
      f"({sym.head(10)['profit'].sum() / blot['pnl'].sum():.0%})")

print("\n" + "=" * 92)
print("BIGGEST INDIVIDUAL TRADES".center(92))
print("=" * 92)
cols = ["symbol", "entry_date", "exit_date", "shares", "entry_price",
        "pnl", "r_multiple", "exit_reason"]
top = blot.nlargest(10, "pnl")[cols].copy()
top["entry_date"] = top["entry_date"].dt.date; top["exit_date"] = top["exit_date"].dt.date
print("\n  10 BEST")
print(top.round(2).to_string(index=False))
bot = blot.nsmallest(10, "pnl")[cols].copy()
bot["entry_date"] = bot["entry_date"].dt.date; bot["exit_date"] = bot["exit_date"].dt.date
print("\n  10 WORST")
print(bot.round(2).to_string(index=False))

print("\n" + "=" * 92)
print("BY HOLDING PERIOD, AND VERSUS DOING NOTHING".center(92))
print("=" * 92)
for label, lo in [("1 year", "2025-09-10"), ("3 years", "2023-09-11"),
                  ("5 years", "2021-09-10"), ("10 years", "2016-09-12"),
                  ("20 years", None)]:
    uni = {s: f.loc[lo:] for s, f in frames.items()}
    bm = {t: f.loc[lo:] for t, f in benchmarks.items()}
    p, c, b = run_config(BEST, uni, bm, starting_equity=START)
    s = bm["SPY"]["close"] / bm["SPY"]["close"].iloc[0]
    print(f"\n  {label} (to 2026-09-09)")
    print(f"    strategy   {len(b):>4} trades   {money(float(c.iloc[-1])):>12}   "
          f"profit {money(float(c.iloc[-1]) - START):>11}   {p.cagr:>6.1%} cagr   "
          f"{p.max_drawdown:>5.1%} maxDD")
    print(f"    SPY hold   {'':>4}          {money(START * float(s.iloc[-1])):>12}   "
          f"profit {money(START * (float(s.iloc[-1]) - 1)):>11}   "
          f"{metrics.cagr(s):>6.1%} cagr   {metrics.max_drawdown(s):>5.1%} maxDD")

blot.to_csv("trades_best.csv", index=False)
curve.to_csv("equity_best.csv")
print("\n\nwrote trades_best.csv and equity_best.csv")
