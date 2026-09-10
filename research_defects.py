"""Quantify the engine defects found by reading the exit and entry code.

Nothing here is fixed yet - this measures how much each defect actually costs,
so the fixes go where the money is rather than where the code looks untidy.
"""

from __future__ import annotations

import pandas as pd

import data as data_mod
from backtester import Backtester
from strategy import StrategyConfig, prepare_symbol, regime_series, size_position

frames = data_mod.load_csv_dir("bars")
benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ")}


class Instrumented(Backtester):
    """Same engine, but it records the entries it turned away and why."""

    def run(self, universe, bmarks):
        self.skipped_for_cash = 0
        self.skipped_for_slots = 0
        self.taken = 0
        self.cash_short = []
        return super().run(universe, bmarks)


# Re-run the entry loop with counters by monkey-patching the cash test.
def instrumented_run(cfg, label):
    engine = Instrumented(cfg)
    prepared = {s: prepare_symbol(f, cfg) for s, f in frames.items()}
    regime = regime_series(benchmarks, cfg)
    calendar = benchmarks["SPY"].index

    cash = engine.starting_equity
    open_positions, closed = {}, []
    taken = skipped_cash = skipped_slots = 0
    shortfall = []

    for date in calendar:
        for symbol in list(open_positions):
            position = open_positions[symbol]
            if date <= position.entry_date or date not in prepared[symbol].index:
                continue
            cash += engine._manage_position(position, prepared[symbol].loc[date], date)
            if position.open_shares == 0:
                del open_positions[symbol]

        slots = cfg.max_open_positions - len(open_positions)
        if bool(regime.get(date, False)):
            equity_now = engine._mark_to_market(cash, open_positions, prepared, date)
            for symbol, bar in engine._candidates(prepared, open_positions, date):
                pos = engine._open_position(symbol, bar, date, equity_now)
                if pos is None:
                    continue
                if slots <= 0:
                    skipped_slots += 1
                    continue
                cost = engine._buy_cost(pos.entry_price, pos.shares)
                if cost > cash:
                    skipped_cash += 1
                    shortfall.append(cash / cost if cost else 0.0)
                    continue
                cash -= cost
                open_positions[symbol] = pos
                taken += 1
                slots -= 1

    total = taken + skipped_cash + skipped_slots
    print(f"\n{label}")
    print(f"  signals reaching the entry gate : {total:,}")
    print(f"  taken                           : {taken:,} ({taken/total:.1%})")
    print(f"  turned away, no free slot       : {skipped_slots:,} ({skipped_slots/total:.1%})")
    print(f"  turned away, not enough cash    : {skipped_cash:,} ({skipped_cash/total:.1%})")
    if shortfall:
        s = pd.Series(shortfall)
        print(f"    of those, median affordable share of the intended size: {s.median():.0%}")
        print(f"    could have afforded >=50% of intended size in {(s >= 0.5).mean():.0%} of cases")
    return skipped_cash


print("=" * 78)
print("DEFECT 1: entries dropped for lack of cash instead of being sized down")
print("=" * 78)
base = StrategyConfig(name="risk 0.5%")
instrumented_run(base, "risk 0.5% (the default)")
instrumented_run(base.variant("risk 1.0%", risk_pct=0.010), "risk 1.0%")
instrumented_run(base.variant("risk 1.5%", risk_pct=0.015), "risk 1.5%")
print("\n  -> A trader short of cash buys a smaller position. The engine refuses the")
print("     trade outright, so raising risk_pct silently deletes signals. That is")
print("     what made 'more risk' look harmful rather than merely more volatile.")

print("\n" + "=" * 78)
print("DEFECT 2: scale_fraction=0 still sells a share")
print("=" * 78)
cfg = base.variant("trail only", exit_mode="scale_out", scale_fraction=0.0)
shares = 300
tranche = max(1, int(round(shares * cfg.scale_fraction)))
print(f"  scale_fraction=0.0 on a {shares}-share position sells {tranche} share(s)")
print("  -> `max(1, ...)` was meant to stop a rounding-to-zero tranche, but it also")
print("     forces a sale when the config asks for no tranche at all. The position")
print("     is then marked scaled, which is the only way the trail ever switches on.")

print("\n" + "=" * 78)
print("DEFECT 3: the trail cannot start until price reaches scale_r")
print("=" * 78)
print("  In _manage_position the trail block is guarded by `if position.scaled`.")
print("  A trade that runs to 1.9R and rolls over never gets a trailing stop at all -")
print("  it rides the original stop all the way back down. There is no way to say")
print("  'trail from entry' in the current config.")

print("\n" + "=" * 78)
print("DEFECT 4: how much the time stop is really doing")
print("=" * 78)
for target in (4.0, 8.0, 12.0):
    cfg = base.variant(f"{target:.0f}R", target_r=target)
    engine = Backtester(cfg)
    curve, blot = engine.run(frames, benchmarks)
    counts = blot["exit_reason"].value_counts()
    ts = counts.get("time_stop", 0)
    print(f"  {target:>4.0f}R target: {len(blot):>4} trades | "
          f"stop {counts.get('stop', 0):>4} | target {counts.get('target', 0):>4} | "
          f"time_stop {ts:>4} ({ts/len(blot):.0%})")
    tsr = blot.loc[blot["exit_reason"] == "time_stop", "r_multiple"]
    if len(tsr):
        print(f"              time-stopped trades averaged {tsr.mean():+.2f}R, "
              f"{(tsr > 0).mean():.0%} of them profitable")
print("\n  max_hold_days counts CALENDAR days, so 120 is about 83 trading days.")
