"""Manage positions after entry: reconcile, protect, trail, and time out.

`trade_executor` opens positions and attaches a stop and a take-profit. Those
are two independent orders, not an OCO pair, so nothing cancels the sibling when
one of them fills. Left alone that is not a cosmetic problem: a filled target
leaves a live stop order for shares that are no longer held, and if it triggers
the account ends up short a stock it never meant to sell. Reconciliation is what
makes the bracket safe, and it has to keep working across restarts, so state
lives in a file rather than in memory.

The loop also owns the two exit rules the broker cannot express: the 250-bar
time stop, and the trailing stop for configs that use one.

Run it once per session, after the close:

    python3 position_manager.py --data ./bars              # dry run
    python3 position_manager.py --data ./bars --live       # acts on the account
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

import pandas as pd

from strategy import DEFAULT_PRESET, PRESETS, StrategyConfig, preset, prepare_symbol

STATE_FILE = Path("positions_state.json")


# ---------------------------------------------------------------------------
# Persisted state
# ---------------------------------------------------------------------------

@dataclass
class ManagedPosition:
    """What the manager needs to remember about a position between runs.

    The broker knows the share count and the average price; it does not know the
    stop distance that defined 1R, how many bars the trade has been open, or how
    high it has run. Those are the strategy's, so they are persisted here.
    """
    symbol: str
    entry_date: str
    entry_price: float
    shares: int
    risk_per_share: float
    stop_price: float
    highest_high: float
    bars_held: int = 0
    trailing: bool = False
    stop_order_id: str | None = None
    target_order_id: str | None = None

    def peak_r(self) -> float:
        if self.risk_per_share <= 0:
            return 0.0
        return (self.highest_high - self.entry_price) / self.risk_per_share


def load_state(path: Path = STATE_FILE) -> dict[str, ManagedPosition]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {s: ManagedPosition(**d) for s, d in raw.items()}


def save_state(state: dict[str, ManagedPosition], path: Path = STATE_FILE) -> None:
    path.write_text(json.dumps({s: asdict(p) for s, p in state.items()}, indent=2))


# ---------------------------------------------------------------------------
# Broker surface the manager needs
# ---------------------------------------------------------------------------

@dataclass
class BrokerOrder:
    id: str
    symbol: str
    kind: str          # "stop" | "limit"
    qty: int
    price: float


class ManagedDryRunBroker:
    """An in-memory account, so the loop can be exercised without a broker."""

    def __init__(self, positions: dict[str, int] | None = None,
                 orders: list[BrokerOrder] | None = None):
        self._positions = dict(positions or {})
        self._orders = list(orders or [])
        self._next = 1
        self.actions: list[str] = []

    def positions(self) -> dict[str, int]:
        return {s: q for s, q in self._positions.items() if q != 0}

    def open_orders(self, symbol: str) -> list[BrokerOrder]:
        return [o for o in self._orders if o.symbol == symbol]

    def cancel_order(self, order_id: str) -> None:
        self._orders = [o for o in self._orders if o.id != order_id]
        self.actions.append(f"cancel {order_id}")

    def submit_stop(self, symbol: str, qty: int, stop_price: float) -> str:
        oid = f"stop-{self._next}"; self._next += 1
        self._orders.append(BrokerOrder(oid, symbol, "stop", qty, stop_price))
        self.actions.append(f"stop {symbol} {qty} @ {stop_price:.2f}")
        return oid

    def submit_market_sell(self, symbol: str, qty: int) -> str:
        oid = f"mkt-{self._next}"; self._next += 1
        self._positions[symbol] = self._positions.get(symbol, 0) - qty
        self.actions.append(f"sell {symbol} {qty} at market")
        return oid


class AlpacaManagedBroker:
    """Alpaca implementation of the same surface. Imported lazily."""

    def __init__(self, api_key: str, api_secret: str, paper: bool = True):
        from alpaca.trading.client import TradingClient
        self.client = TradingClient(api_key, api_secret, paper=paper)

    def positions(self) -> dict[str, int]:
        return {p.symbol: int(float(p.qty)) for p in self.client.get_all_positions()}

    def open_orders(self, symbol: str) -> list[BrokerOrder]:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        out = []
        for o in self.client.get_orders(filter=req):
            price = o.stop_price or o.limit_price
            kind = "stop" if o.stop_price else "limit"
            out.append(BrokerOrder(str(o.id), o.symbol, kind, int(float(o.qty)),
                                   float(price) if price else 0.0))
        return out

    def cancel_order(self, order_id: str) -> None:
        self.client.cancel_order_by_id(order_id)

    def submit_stop(self, symbol: str, qty: int, stop_price: float) -> str:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import StopOrderRequest
        o = self.client.submit_order(order_data=StopOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC, stop_price=round(stop_price, 2)))
        return str(o.id)

    def submit_market_sell(self, symbol: str, qty: int) -> str:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest
        o = self.client.submit_order(order_data=MarketOrderRequest(
            symbol=symbol, qty=qty, side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY))
        return str(o.id)


# ---------------------------------------------------------------------------
# The manager
# ---------------------------------------------------------------------------

class PositionManager:
    def __init__(self, cfg: StrategyConfig, broker, bars: dict[str, pd.DataFrame]):
        self.cfg = cfg
        self.broker = broker
        self.bars = bars
        self.log: list[str] = []

    def note(self, msg: str) -> None:
        self.log.append(msg)
        print(f"    {msg}")

    # -- step 1: make the account and the state agree ----------------------

    def reconcile(self, state: dict[str, ManagedPosition]) -> dict[str, ManagedPosition]:
        """Drop closed positions, cancel their orphaned orders, resize partials.

        Cancelling first is the point of the whole loop: a target that filled
        leaves a live stop for shares that are gone, and a stop order with no
        position behind it opens a short if it ever triggers.
        """
        held = self.broker.positions()
        for symbol in list(state):
            tracked = state[symbol]
            actual = held.get(symbol, 0)

            if actual <= 0:
                for order in self.broker.open_orders(symbol):
                    self.broker.cancel_order(order.id)
                    self.note(f"{symbol}: position closed - cancelled orphaned "
                              f"{order.kind} order {order.id}")
                del state[symbol]
                continue

            if actual != tracked.shares:
                self.note(f"{symbol}: size changed {tracked.shares} -> {actual} "
                          f"(partial fill); re-protecting")
                tracked.shares = actual
                self._replace_stop(tracked, tracked.stop_price)

        for symbol, qty in held.items():
            if symbol not in state:
                self.note(f"{symbol}: {qty} shares held with no tracked state - "
                          f"not managed, needs a manual stop")
        return state

    # -- step 2: the exits the broker cannot express -----------------------

    def advance(self, state: dict[str, ManagedPosition], date: pd.Timestamp) -> None:
        for symbol, pos in list(state.items()):
            frame = self.bars.get(symbol)
            if frame is None or date not in frame.index:
                continue
            bar = frame.loc[date]
            pos.bars_held += 1
            pos.highest_high = max(pos.highest_high, float(bar["high"]))

            if self.cfg.trail_from_r is not None:
                self._maybe_trail(pos, bar)

            if pos.bars_held >= self.cfg.max_hold_bars:
                self._time_stop(state, pos)

    def _maybe_trail(self, pos: ManagedPosition, bar) -> None:
        if not pos.trailing:
            if pos.peak_r() < self.cfg.trail_from_r:
                return
            pos.trailing = True
            self.note(f"{pos.symbol}: reached {pos.peak_r():.1f}R - trail armed")
        atr = float(bar["atr"]) if pd.notna(bar["atr"]) else 0.0
        if atr <= 0:
            return
        trail = pos.highest_high - self.cfg.trail_atr_mult * atr
        if trail > pos.stop_price:          # a stop is raised, never lowered
            self.note(f"{pos.symbol}: stop {pos.stop_price:.2f} -> {trail:.2f}")
            self._replace_stop(pos, trail)

    def _time_stop(self, state: dict[str, ManagedPosition], pos: ManagedPosition) -> None:
        self.note(f"{pos.symbol}: {pos.bars_held} bars held - closing at market")
        for order in self.broker.open_orders(pos.symbol):
            self.broker.cancel_order(order.id)
        self.broker.submit_market_sell(pos.symbol, pos.shares)
        state.pop(pos.symbol, None)

    def _replace_stop(self, pos: ManagedPosition, new_stop: float) -> None:
        """Cancel the old stop before submitting the new one.

        The other order is left alone: cancelling the take-profit here would
        remove the exit that produced the backtested results.
        """
        for order in self.broker.open_orders(pos.symbol):
            if order.kind == "stop":
                self.broker.cancel_order(order.id)
        pos.stop_price = new_stop
        pos.stop_order_id = self.broker.submit_stop(pos.symbol, pos.shares, new_stop)


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile and manage open positions.")
    parser.add_argument("--data", required=True, help="directory of <SYMBOL>.csv daily bars")
    parser.add_argument("--strategy", default=DEFAULT_PRESET, choices=sorted(PRESETS))
    parser.add_argument("--state", default=str(STATE_FILE))
    parser.add_argument("--live", action="store_true",
                        help="act on the real account (needs ALPACA_API_KEY/SECRET)")
    args = parser.parse_args(argv)

    import data as data_mod
    cfg = preset(args.strategy)
    frames = data_mod.load_csv_dir(args.data)
    for t in ("SPY", "QQQ"):
        frames.pop(t, None)
    prepared = {s: prepare_symbol(f, cfg) for s, f in frames.items()}

    state = load_state(Path(args.state))
    if args.live:
        import os
        key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_API_SECRET")
        if not key or not secret:
            print("error: --live needs ALPACA_API_KEY and ALPACA_API_SECRET", file=sys.stderr)
            return 2
        broker = AlpacaManagedBroker(key, secret, paper=True)
    else:
        broker = ManagedDryRunBroker(positions={s: p.shares for s, p in state.items()})

    print(f"=== manage | config '{cfg.name}' | {len(state)} tracked position(s) "
          f"| {'LIVE' if args.live else 'DRY RUN'} ===")
    manager = PositionManager(cfg, broker, prepared)
    print("  reconciling...")
    state = manager.reconcile(state)
    latest = max((f.index[-1] for f in prepared.values()), default=None)
    if latest is not None:
        print(f"  advancing to {latest.date()}...")
        manager.advance(state, latest)
    save_state(state, Path(args.state))
    print(f"=== {len(manager.log)} action(s); {len(state)} position(s) still managed ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
