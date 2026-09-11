"""One entry point for a trading session: manage first, then scan.

The order is the whole point. Position management closes trades that have hit
their time limit and frees their slots; the scan then fills the slots that are
genuinely free. Run the other way round, new positions get opened against a slot
count that is about to change, and capital is committed to entries that should
have gone to better candidates.

The two steps also share one broker connection, so the scan sees the account as
the manager just left it rather than a snapshot from before it ran.

If management fails, the scan does not run. Opening new risk while the state of
existing positions is unknown is the one failure this must never turn into.

    python3 run_session.py --data ./bars                 # dry run
    python3 run_session.py --data ./bars --live          # acts on the account
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback
from pathlib import Path

import position_manager as pm
import trade_executor as te
from strategy import DEFAULT_PRESET, PRESETS, preset, prepare_symbol

LOG_FILE = Path("session.log")


class Tee:
    """Write session output to the terminal and to a log at the same time.

    A scheduled run has nobody watching it, so the log is the only record of
    what was decided and why.
    """

    def __init__(self, path: Path):
        self.handle = path.open("a", encoding="utf-8")

    def write(self, text: str) -> None:
        sys.__stdout__.write(text)
        self.handle.write(text)

    def flush(self) -> None:
        sys.__stdout__.flush()
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()


# ---------------------------------------------------------------------------
# One broker satisfying both surfaces
# ---------------------------------------------------------------------------

class SessionDryRunBroker(pm.ManagedDryRunBroker):
    """Adds the entry-side surface to the managed dry-run account."""

    def __init__(self, equity: float = 100_000.0, positions=None, orders=None):
        super().__init__(positions=positions, orders=orders)
        self._equity = equity
        self.planned: list[te.OrderPlan] = []

    def equity(self) -> float:
        return self._equity

    def open_symbols(self) -> set[str]:
        return set(self.positions())

    def submit_bracket(self, plan: te.OrderPlan) -> str:
        print(f"    [DRY RUN] would submit -> {plan.describe()}")
        self._positions[plan.symbol] = self._positions.get(plan.symbol, 0) + plan.shares
        self.planned.append(plan)
        return f"dry-{plan.symbol}"


class SessionAlpacaBroker(pm.AlpacaManagedBroker):
    """Both surfaces over a single Alpaca client, so the two steps agree."""

    def equity(self) -> float:
        return float(self.client.get_account().equity)

    def open_symbols(self) -> set[str]:
        return set(self.positions())

    def submit_bracket(self, plan: te.OrderPlan) -> str:
        # Reuse the executor's implementation rather than restating the order
        # construction, so entry behaviour cannot drift between the two paths.
        return te.AlpacaBroker.submit_bracket(self, plan)


# ---------------------------------------------------------------------------

def run_session(cfg, broker, frames, prepared, benchmarks, state_path: Path) -> int:
    stamp = dt.datetime.now()
    print(f"\n{'=' * 78}")
    print(f"SESSION {stamp:%Y-%m-%d %H:%M:%S}  |  strategy '{cfg.name}'")
    print("=" * 78)

    # --- Step 1: manage what is already open ------------------------------
    print("\n[1/2] MANAGE OPEN POSITIONS")
    state = pm.load_state(state_path)
    print(f"  {len(state)} tracked position(s)")
    manager = pm.PositionManager(cfg, broker, prepared)
    try:
        state = manager.reconcile(state)
        latest = max((f.index[-1] for f in prepared.values()), default=None)
        if latest is not None:
            manager.advance(state, latest)
        pm.save_state(state, state_path)
    except Exception:
        # Never open new risk while the existing book is in an unknown state.
        print("  !! management failed - skipping the scan entirely", file=sys.stderr)
        traceback.print_exc()
        return 1
    print(f"  {len(manager.log)} action(s) taken; {len(state)} position(s) managed")

    # --- Step 2: look for new entries -------------------------------------
    print("\n[2/2] SCAN FOR NEW ENTRIES")
    try:
        submitted = te.trade_once(frames, benchmarks, broker, cfg)
    except Exception:
        print("  !! scan failed; managed positions are unaffected", file=sys.stderr)
        traceback.print_exc()
        return 1

    # Newly opened positions become managed from the next session onward.
    for plan in submitted:
        state[plan.symbol] = pm.ManagedPosition(
            symbol=plan.symbol, entry_date=str(stamp.date()),
            entry_price=plan.entry_price, shares=plan.shares,
            risk_per_share=plan.risk_dollars / plan.shares if plan.shares else 0.0,
            stop_price=plan.stop_price, highest_high=plan.entry_price)
    pm.save_state(state, state_path)

    print(f"\n{'=' * 78}")
    print(f"DONE  |  {len(submitted)} new position(s)  |  {len(state)} total managed")
    print("=" * 78)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run one full trading session.")
    parser.add_argument("--data", required=True, help="directory of <SYMBOL>.csv daily bars")
    parser.add_argument("--strategy", default=DEFAULT_PRESET, choices=sorted(PRESETS))
    parser.add_argument("--state", default=str(pm.STATE_FILE))
    parser.add_argument("--log", default=str(LOG_FILE))
    parser.add_argument("--equity", type=float, default=100_000.0,
                        help="assumed equity for dry runs")
    parser.add_argument("--live", action="store_true",
                        help="act on the real account (needs ALPACA_API_KEY/SECRET)")
    args = parser.parse_args(argv)

    import data as data_mod

    cfg = preset(args.strategy)
    frames = data_mod.load_csv_dir(args.data)
    benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ") if t in frames}
    if "SPY" not in benchmarks:
        print("error: SPY.csv is required for the regime gate", file=sys.stderr)
        return 2
    prepared = {s: prepare_symbol(f, cfg) for s, f in frames.items()}

    state_path = Path(args.state)
    if args.live:
        import os
        key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_API_SECRET")
        if not key or not secret:
            print("error: --live needs ALPACA_API_KEY and ALPACA_API_SECRET", file=sys.stderr)
            return 2
        broker = SessionAlpacaBroker(key, secret, paper=True)
    else:
        state = pm.load_state(state_path)
        broker = SessionDryRunBroker(equity=args.equity,
                                     positions={s: p.shares for s, p in state.items()})

    tee = Tee(Path(args.log))
    sys.stdout = tee
    try:
        return run_session(cfg, broker, frames, prepared, benchmarks, state_path)
    finally:
        sys.stdout = sys.__stdout__
        tee.close()


if __name__ == "__main__":
    raise SystemExit(main())
