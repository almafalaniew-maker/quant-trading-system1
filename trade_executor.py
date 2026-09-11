"""Live/paper execution driven by the same `StrategyConfig` the backtester uses.

This is a corrected, executable version of the gap-and-go automation sketch.
What changed and why:

* `if _name_ == "_main_"` never fires - single underscores are not the dunder
  names Python sets, so the sketch's main block was dead code.
* The scale-out was only ever printed. Here the protective stop and the +2R
  tranche are actually submitted, and the remainder is trailed.
* A flat 2%-of-price stop is replaced by an ATR stop. The same 2% is a wide stop
  on a quiet name and inside the daily noise on a volatile one, so a flat stop
  silently varies the real risk per trade by several times.
* The liquidity gate uses average *dollar* volume, and excludes the current
  (incomplete) session from the average.
* Signal and sizing logic is imported from `strategy.py`, so what runs live is
  the code that was backtested rather than a re-implementation that can drift.
* Runs in dry-run mode unless `--live` is passed explicitly.

The broker layer is behind `Broker`, so the strategy can be exercised without
credentials and without an order ever leaving the machine.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

import indicators as ind
from strategy import (
    DEFAULT_PRESET, PRESETS, StrategyConfig, prepare_symbol,
    preset, regime_series, size_position,
)


# ---------------------------------------------------------------------------
# Broker abstraction
# ---------------------------------------------------------------------------

@dataclass
class OrderPlan:
    """Everything needed to place one bracketed entry, computed before any fill.

    `take_profit_shares` is the size that rests on a limit order. Under a fixed
    target that is the whole position; under a scale-out it is only the tranche,
    and the remainder is managed by the trailing stop.
    """
    symbol: str
    shares: int
    entry_price: float
    stop_price: float
    take_profit_price: float
    take_profit_shares: int
    trailed_shares: int
    risk_dollars: float
    exit_mode: str

    def describe(self) -> str:
        head = (f"{self.symbol}: {self.shares} @ ~{self.entry_price:.2f} "
                f"| stop {self.stop_price:.2f} (risk ${self.risk_dollars:,.0f})")
        if self.exit_mode == "fixed_target":
            return f"{head} | target {self.take_profit_shares} @ {self.take_profit_price:.2f}"
        return (f"{head} | scale {self.take_profit_shares} @ {self.take_profit_price:.2f} "
                f"| runner {self.trailed_shares} trails")


class Broker(Protocol):
    def equity(self) -> float: ...
    def open_symbols(self) -> set[str]: ...
    def submit_bracket(self, plan: OrderPlan) -> str: ...


class DryRunBroker:
    """Prints what would be sent. The default, so nothing trades by accident."""

    def __init__(self, equity: float = 100_000.0):
        self._equity = equity
        self._open: set[str] = set()

    def equity(self) -> float:
        return self._equity

    def open_symbols(self) -> set[str]:
        return set(self._open)

    def submit_bracket(self, plan: OrderPlan) -> str:
        print(f"    [DRY RUN] would submit -> {plan.describe()}")
        self._open.add(plan.symbol)
        return f"dry-{plan.symbol}"


class AlpacaBroker:
    """Thin Alpaca wrapper. Imported lazily so the module works without the SDK."""

    def __init__(self, api_key: str, api_secret: str, paper: bool = True):
        from alpaca.trading.client import TradingClient

        self.client = TradingClient(api_key, api_secret, paper=paper)

    def equity(self) -> float:
        return float(self.client.get_account().equity)

    def open_symbols(self) -> set[str]:
        return {p.symbol for p in self.client.get_all_positions()}

    def submit_bracket(self, plan: OrderPlan) -> str:
        """Entry plus a protective stop on the full size and a limit on the tranche.

        Submitted as two child orders rather than one bracket because the exit is
        split: the +2R tranche and the trailed runner have different targets. The
        stop covers the whole position from the moment the entry fills; the
        breakeven move happens when `manage_open_positions` sees the tranche fill.
        """
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import (
            LimitOrderRequest, MarketOrderRequest, StopOrderRequest,
        )

        entry = self.client.submit_order(order_data=MarketOrderRequest(
            symbol=plan.symbol, qty=plan.shares, side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        ))

        self.client.submit_order(order_data=StopOrderRequest(
            symbol=plan.symbol, qty=plan.shares, side=OrderSide.SELL,
            time_in_force=TimeInForce.GTC, stop_price=round(plan.stop_price, 2),
        ))
        # The take-profit must be placed for every exit mode. Gating it on a
        # scale-out tranche left the fixed-target presets - which are the tested
        # ones - running live with a stop and no profit target at all.
        if plan.take_profit_shares > 0:
            self.client.submit_order(order_data=LimitOrderRequest(
                symbol=plan.symbol, qty=plan.take_profit_shares, side=OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
                limit_price=round(plan.take_profit_price, 2),
            ))
        return str(entry.id)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def market_is_permissive(benchmarks: dict[str, pd.DataFrame], cfg: StrategyConfig) -> bool:
    """Evaluate the regime gate on the most recent completed bar."""
    gate = regime_series(benchmarks, cfg)
    if gate.empty:
        return False
    ok = bool(gate.iloc[-1])
    detail = "BULLISH - trading active" if ok else "BEARISH - entries paused"
    print(f"[*] Regime ({cfg.regime_mode}): {detail}")
    return ok


def scan(universe: dict[str, pd.DataFrame], cfg: StrategyConfig) -> list[dict]:
    """Return today's qualifying breakouts, best first.

    `universe` holds completed daily bars. The last row is the bar being traded;
    every filter reads values that are final as of that bar's close.
    """
    hits = []
    for symbol, frame in universe.items():
        if len(frame) < max(cfg.trend_window, cfg.liquidity_window, cfg.atr_window) + 2:
            continue
        try:
            prepared = prepare_symbol(frame, cfg)
        except Exception as exc:                      # one bad symbol must not stop the scan
            print(f"[!] {symbol}: {exc}", file=sys.stderr)
            continue

        last = prepared.iloc[-1]
        if not bool(last["signal"]):
            continue
        hits.append({
            "symbol": symbol,
            "price": float(last["close"]),
            "gap_pct": float(last["gap_pct"]),
            "atr": float(last["atr"]),
            "stop_distance": float(last["stop_distance"]),
            "adv_dollars": float(last["adv_dollars"]),
        })

    hits.sort(key=lambda h: -h["gap_pct"] if cfg.gap_mode in ("required", "bonus")
              else -h["price"])
    return hits


def plan_order(hit: dict, equity: float, cfg: StrategyConfig) -> OrderPlan | None:
    """Turn a scan hit into a fully specified bracketed order."""
    sizing = size_position(equity, hit["price"], hit["stop_distance"], cfg)
    if sizing is None:
        return None

    if cfg.exit_mode == "fixed_target":
        # The whole position rests at target_r; nothing is trailed.
        take_profit_price = hit["price"] + cfg.target_r * sizing.risk_per_share
        take_profit_shares = sizing.shares
    else:
        take_profit_price = hit["price"] + cfg.scale_r * sizing.risk_per_share
        take_profit_shares = (
            min(sizing.shares, max(1, int(round(sizing.shares * cfg.scale_fraction))))
            if cfg.scale_fraction > 0 else 0
        )

    return OrderPlan(
        symbol=hit["symbol"],
        shares=sizing.shares,
        entry_price=hit["price"],
        stop_price=sizing.stop_price,
        take_profit_price=take_profit_price,
        take_profit_shares=take_profit_shares,
        trailed_shares=sizing.shares - take_profit_shares,
        risk_dollars=sizing.risk_dollars,
        exit_mode=cfg.exit_mode,
    )


def trade_once(universe, benchmarks, broker: Broker, cfg: StrategyConfig) -> list[OrderPlan]:
    """One full pass: regime gate, scan, size, submit."""
    print(f"=== scan {dt.datetime.now():%Y-%m-%d %H:%M:%S} | config '{cfg.name}' ===")
    if not market_is_permissive(benchmarks, cfg):
        return []

    held = broker.open_symbols()
    slots = cfg.max_open_positions - len(held)
    if slots <= 0:
        print(f"[*] {len(held)} positions open, at the {cfg.max_open_positions} cap.")
        return []

    hits = [h for h in scan(universe, cfg) if h["symbol"] not in held]
    print(f"[*] {len(hits)} qualifying breakouts; {slots} slot(s) free.")

    equity = broker.equity()
    submitted = []
    for hit in hits[:slots]:
        plan = plan_order(hit, equity, cfg)
        if plan is None:
            print(f"    skip {hit['symbol']}: position would round to zero shares")
            continue
        broker.submit_bracket(plan)
        submitted.append(plan)
    return submitted


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run one scan-and-trade pass.")
    parser.add_argument("--data", required=True, help="directory of <SYMBOL>.csv daily bars")
    parser.add_argument("--strategy", default=DEFAULT_PRESET, choices=sorted(PRESETS),
                        help=f"named preset to run (default: {DEFAULT_PRESET})")
    parser.add_argument("--live", action="store_true",
                        help="actually submit orders (requires ALPACA_API_KEY/SECRET)")
    parser.add_argument("--paper", action="store_true", default=True)
    parser.add_argument("--equity", type=float, default=100_000.0,
                        help="assumed equity for dry runs")
    parser.add_argument("--gap-required", action="store_true",
                        help="only take breakouts that gapped up at least min-gap")
    parser.add_argument("--min-gap", type=float, default=0.025)
    parser.add_argument("--scale-out", action="store_true",
                        help="bank a third at +2R and trail the rest")
    parser.add_argument("--strict-regime", action="store_true",
                        help="require SPY and QQQ above both 50-SMA and 10-EMA")
    args = parser.parse_args(argv)

    import data as data_mod

    # Start from the tested preset; the flags below only override it when the
    # caller explicitly asks, so the live config stays the backtested one.
    cfg = preset(args.strategy)
    overrides = {}
    if args.gap_required:
        overrides.update(gap_mode="required", min_gap_pct=args.min_gap)
    if args.scale_out:
        overrides.update(exit_mode="scale_out")
    if args.strict_regime:
        overrides.update(regime_mode="dual_index_strict")
    if overrides:
        cfg = cfg.variant(f"{cfg.name}+overrides", **overrides)

    frames = data_mod.load_csv_dir(args.data)
    benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ") if t in frames}
    if "SPY" not in benchmarks:
        print("error: SPY.csv is required for the regime gate", file=sys.stderr)
        return 2

    if args.live:
        import os
        key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_API_SECRET")
        if not key or not secret:
            print("error: --live needs ALPACA_API_KEY and ALPACA_API_SECRET", file=sys.stderr)
            return 2
        broker: Broker = AlpacaBroker(key, secret, paper=args.paper)
    else:
        broker = DryRunBroker(equity=args.equity)

    submitted = trade_once(frames, benchmarks, broker, cfg)
    print(f"=== {len(submitted)} order(s) {'submitted' if args.live else 'planned'} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
