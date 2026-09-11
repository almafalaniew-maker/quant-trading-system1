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
import os
import sys
import traceback
from pathlib import Path

import position_manager as pm
import safety
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

    def clock(self):
        """The venue's own clock - never the local one. A server in the wrong
        timezone, or a market holiday, must not be able to open positions."""
        return self.client.get_clock()

    def submit_bracket(self, plan: te.OrderPlan) -> str:
        # Reuse the executor's implementation rather than restating the order
        # construction, so entry behaviour cannot drift between the two paths.
        return te.AlpacaBroker.submit_bracket(self, plan)


class GuardedBroker:
    """Wraps a broker so no order reaches it without passing the safety checks.

    Sizing already bounds every one of these. That is the reason to check again
    here: this is the layer that catches the case where the sizing code itself
    is what went wrong, and it is the last point before real money moves.
    """

    def __init__(self, inner, limits: safety.Limits, open_risk: float = 0.0):
        self.inner = inner
        self.limits = limits
        self.open_risk = open_risk
        self.rejected: list[safety.Check] = []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def submit_bracket(self, plan) -> str | None:
        equity = self.inner.equity()
        order_check = safety.validate_order(plan, equity, self.limits)
        if not order_check.passed:
            print(f"    REJECTED {order_check}")
            self.rejected.append(order_check)
            return None
        risk_check = safety.check_portfolio_risk(
            self.open_risk, plan.risk_dollars, equity, self.limits)
        if not risk_check.passed:
            print(f"    REJECTED {plan.symbol} - {risk_check.detail}")
            self.rejected.append(risk_check)
            return None
        self.open_risk += plan.risk_dollars
        return self.inner.submit_bracket(plan)


# ---------------------------------------------------------------------------

def run_session(cfg, broker, frames, prepared, benchmarks, state_path: Path,
                live: bool = False, limits: safety.Limits | None = None,
                ledger_path: Path = safety.LEDGER_FILE) -> int:
    stamp = dt.datetime.now()
    limits = limits or safety.Limits()
    mode = "LIVE - REAL ORDERS" if live else "dry run"
    print(f"\n{'=' * 78}")
    print(f"SESSION {stamp:%Y-%m-%d %H:%M:%S}  |  strategy '{cfg.name}'  |  {mode}")
    print("=" * 78)

    # --- Step 0: refuse to trade unless every rail is clear ----------------
    print("\n[0/2] PREFLIGHT")
    ledger = safety.Ledger.load(ledger_path)
    today = str(stamp.date())
    try:
        equity = broker.equity()
        open_count = len(broker.open_symbols())
        clock = broker.clock() if live and hasattr(broker, "clock") else None
    except Exception:
        print("  !! could not read the account - refusing to trade", file=sys.stderr)
        traceback.print_exc()
        return 1

    result = safety.preflight(live=live, equity=equity, open_count=open_count,
                              clock=clock, ledger=ledger, today=today, limits=limits)
    print(result.report())
    if not result.ok:
        return 2

    if ledger.day_start_equity <= 0 or ledger.last_session_date != today:
        ledger.day_start_equity = equity
    ledger.high_water = max(ledger.high_water, equity)

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
    open_risk = sum(p.shares * p.risk_per_share for p in state.values())
    guarded = GuardedBroker(broker, limits, open_risk=open_risk)
    try:
        submitted = te.trade_once(frames, benchmarks, guarded, cfg)
        submitted = [p for p in submitted if p is not None]
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

    ledger.last_session_date = today
    ledger.save(ledger_path)

    print(f"\n{'=' * 78}")
    print(f"DONE  |  {len(submitted)} new position(s)  |  {len(state)} total managed"
          + (f"  |  {len(guarded.rejected)} rejected by safety" if guarded.rejected else ""))
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
                        help="send real orders (also needs QTS_ALLOW_LIVE=yes "
                             "and ALPACA_API_KEY/ALPACA_API_SECRET)")
    parser.add_argument("--ledger", default=str(safety.LEDGER_FILE))
    parser.add_argument("--max-daily-loss", type=float, default=0.06)
    parser.add_argument("--max-drawdown", type=float, default=0.30)
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
        broker = SessionAlpacaBroker(key, secret, paper=not os.getenv("QTS_REAL_MONEY"))
    else:
        state = pm.load_state(state_path)
        broker = SessionDryRunBroker(equity=args.equity,
                                     positions={s: p.shares for s, p in state.items()})

    tee = Tee(Path(args.log))
    sys.stdout = tee
    try:
        limits = safety.Limits(max_daily_loss_pct=args.max_daily_loss,
                               max_total_drawdown_pct=args.max_drawdown,
                               max_open_positions=cfg.max_open_positions)
        return run_session(cfg, broker, frames, prepared, benchmarks, state_path,
                           live=args.live, limits=limits,
                           ledger_path=Path(args.ledger))
    finally:
        sys.stdout = sys.__stdout__
        tee.close()


if __name__ == "__main__":
    raise SystemExit(main())
