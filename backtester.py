"""Portfolio-level daily backtester for the breakout system.

Modelling choices, all deliberately pessimistic where the data is ambiguous:

* Entries fill at the close of the signal bar, so nothing an entry depends on
  comes from after the fill.
* Exits are checked from the bar *after* entry onward.
* When a bar's range contains both the stop and the target, the stop is assumed
  to hit first. Daily bars cannot say which came first, and the alternative
  flatters every result.
* A gap through a level fills at the open, not the level. This is where real
  drawdowns come from and it must not be modelled away.
* Every fill pays `cost_bps` of slippage plus commission.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

import metrics
from strategy import StrategyConfig, prepare_symbol, regime_series, size_position


@dataclass
class ExitLeg:
    date: pd.Timestamp
    shares: int
    price: float
    reason: str


@dataclass
class Position:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    risk_per_share: float
    stop_price: float
    initial_shares: int
    initial_risk_dollars: float
    scaled: bool = False
    trailing: bool = False
    bars_held: int = 0
    highest_high: float = 0.0
    realised_pnl: float = 0.0
    legs: list[ExitLeg] = field(default_factory=list)

    @property
    def open_shares(self) -> int:
        return self.shares


class Backtester:
    """Runs one `StrategyConfig` over a universe and returns curve + blotter."""

    def __init__(
        self,
        config: StrategyConfig,
        starting_equity: float = 100_000.0,
        cost_bps: float = 5.0,
        commission_per_share: float = 0.005,
    ):
        self.cfg = config
        self.starting_equity = starting_equity
        self.cost_bps = cost_bps
        self.commission_per_share = commission_per_share

    # -- fills -------------------------------------------------------------

    def _buy_cost(self, price: float, shares: int) -> float:
        slip = price * (self.cost_bps / 10_000.0)
        return (price + slip) * shares + self.commission_per_share * shares

    def _sell_proceeds(self, price: float, shares: int) -> float:
        slip = price * (self.cost_bps / 10_000.0)
        return (price - slip) * shares - self.commission_per_share * shares

    # -- main loop ---------------------------------------------------------

    def run(
        self,
        universe: dict[str, pd.DataFrame],
        benchmarks: dict[str, pd.DataFrame],
        prepared: dict[str, pd.DataFrame] | None = None,
    ) -> tuple[pd.Series, pd.DataFrame]:
        """Run the config over `universe`.

        `prepared` accepts frames whose indicators were computed once elsewhere -
        a walk-forward runs the same config over dozens of overlapping windows,
        and recomputing every indicator each time dominates the runtime. The
        frames must have been prepared with this same config.
        """
        cfg = self.cfg
        if prepared is None:
            prepared = {sym: prepare_symbol(df, cfg) for sym, df in universe.items()}
        regime = regime_series(benchmarks, cfg)
        calendar = benchmarks["SPY"].index

        cash = self.starting_equity
        open_positions: dict[str, Position] = {}
        closed: list[dict] = []
        equity_points: list[float] = []
        invested_days = 0

        for date in calendar:
            # 1) Manage what is already open, using today's bar.
            for symbol in list(open_positions):
                position = open_positions[symbol]
                if date <= position.entry_date:
                    continue
                bar = prepared[symbol].loc[date] if date in prepared[symbol].index else None
                if bar is None:
                    continue
                cash += self._manage_position(position, bar, date)
                if position.open_shares == 0:
                    closed.append(self._blotter_row(position))
                    del open_positions[symbol]

            # 2) Take new entries at today's close, if the regime allows it.
            slots = cfg.max_open_positions - len(open_positions)
            if slots > 0 and bool(regime.get(date, False)):
                equity_now = self._mark_to_market(cash, open_positions, prepared, date)
                for symbol, bar in self._candidates(prepared, open_positions, date):
                    if slots <= 0:
                        break
                    position = self._open_position(symbol, bar, date, equity_now)
                    if position is None:
                        continue
                    cost = self._buy_cost(position.entry_price, position.shares)
                    if cost > cash:
                        # Buy what the cash allows instead of dropping the signal.
                        # Refusing outright deletes 43% of entries at the default
                        # risk budget and 97% at 1.5%, which silently turns a
                        # sizing question into a selection one.
                        per_share = self._buy_cost(position.entry_price, 1)
                        affordable = int(cash // per_share) if per_share > 0 else 0
                        floor = position.shares * cfg.min_fill_fraction
                        if affordable <= 0 or affordable < floor:
                            continue
                        position.shares = affordable
                        position.initial_shares = affordable
                        position.initial_risk_dollars = affordable * position.risk_per_share
                        cost = self._buy_cost(position.entry_price, affordable)
                    cash -= cost
                    open_positions[symbol] = position
                    slots -= 1

            equity = self._mark_to_market(cash, open_positions, prepared, date)
            equity_points.append(equity)
            if open_positions:
                invested_days += 1

        # Close anything still open at the final bar, so the blotter is complete.
        last_date = calendar[-1]
        for symbol, position in list(open_positions.items()):
            frame = prepared[symbol]
            if last_date in frame.index:
                price = float(frame.loc[last_date, "close"])
                cash += self._close_shares(position, position.open_shares, price, last_date, "end_of_test")
                closed.append(self._blotter_row(position))

        curve = pd.Series(equity_points, index=calendar, name="equity")
        blotter = pd.DataFrame(closed)
        self.exposure = invested_days / len(calendar) if len(calendar) else 0.0
        return curve, blotter

    # -- entries -----------------------------------------------------------

    def _candidates(self, prepared, open_positions, date):
        """Signalling symbols for `date`, best first."""
        rows = []
        for symbol, frame in prepared.items():
            if symbol in open_positions or date not in frame.index:
                continue
            bar = frame.loc[date]
            if not bool(bar["signal"]):
                continue
            rows.append((symbol, bar))

        def rank(item):
            symbol, bar = item
            gap = float(bar["gap_pct"]) if pd.notna(bar["gap_pct"]) else 0.0
            if self.cfg.gap_mode in ("required", "bonus"):
                # Strongest gap first: the conviction signal the script keys on.
                return (-gap, symbol)
            thrust = float(bar["close"] / bar["range_high"] - 1.0) if bar["range_high"] else 0.0
            return (-thrust, symbol)

        rows.sort(key=rank)
        return rows

    def _open_position(self, symbol, bar, date, equity) -> Position | None:
        entry_price = float(bar["close"])
        risk_per_share = float(bar["stop_distance"])
        sizing = size_position(equity, entry_price, risk_per_share, self.cfg)
        if sizing is None:
            return None
        return Position(
            symbol=symbol,
            entry_date=date,
            entry_price=entry_price,
            shares=sizing.shares,
            risk_per_share=risk_per_share,
            stop_price=sizing.stop_price,
            initial_shares=sizing.shares,
            initial_risk_dollars=sizing.risk_dollars,
            highest_high=float(bar["high"]),
        )

    # -- exits -------------------------------------------------------------

    def _manage_position(self, position: Position, bar, date) -> float:
        """Walk one open position through one bar; returns cash generated."""
        cfg = self.cfg
        high, low, open_, close = (
            float(bar["high"]), float(bar["low"]), float(bar["open"]), float(bar["close"])
        )
        position.highest_high = max(position.highest_high, high)
        proceeds = 0.0

        # Stop first: a bar that touches both levels is assumed to have hurt.
        if low <= position.stop_price:
            fill = min(open_, position.stop_price)  # gap-through fills at the open
            reason = "stop" if not position.scaled else "trail_stop"
            return proceeds + self._close_shares(position, position.open_shares, fill, date, reason)

        if cfg.exit_mode == "fixed_target":
            target = position.entry_price + cfg.target_r * position.risk_per_share
            if high >= target:
                fill = max(open_, target)
                return proceeds + self._close_shares(position, position.open_shares, fill, date, "target")

        elif cfg.scale_fraction > 0 and not position.scaled:
            # Bank a tranche at scale_r. Only when a fraction is actually asked
            # for - rounding a zero fraction up to one share used to sell stock
            # the config never requested, and marked the position scaled.
            scale_target = position.entry_price + cfg.scale_r * position.risk_per_share
            if high >= scale_target:
                fill = max(open_, scale_target)
                tranche = min(max(1, int(round(position.initial_shares * cfg.scale_fraction))),
                              position.open_shares)
                proceeds += self._close_shares(position, tranche, fill, date, "scale_out")
                position.scaled = True
                if cfg.breakeven_after_scale:
                    position.stop_price = max(position.stop_price, position.entry_price)

        # Trailing stop. Armed either by an explicit trail_from_r threshold or,
        # when that is unset, by a scale-out having happened - the old behaviour.
        if position.open_shares > 0:
            if cfg.trail_from_r is None:
                position.trailing = position.scaled
            elif not position.trailing:
                peak_r = (position.highest_high - position.entry_price) / position.risk_per_share
                position.trailing = peak_r >= cfg.trail_from_r
            if position.trailing:
                atr_now = float(bar["atr"]) if pd.notna(bar["atr"]) else 0.0
                if atr_now > 0:
                    trail = position.highest_high - cfg.trail_atr_mult * atr_now
                    position.stop_price = max(position.stop_price, trail)

        position.bars_held += 1
        if position.open_shares > 0 and position.bars_held >= cfg.max_hold_bars:
            proceeds += self._close_shares(position, position.open_shares, close, date, "time_stop")

        return proceeds

    def _close_shares(self, position: Position, shares: int, price: float, date, reason: str) -> float:
        if shares <= 0:
            return 0.0
        proceeds = self._sell_proceeds(price, shares)
        position.realised_pnl += proceeds - self._buy_cost(position.entry_price, shares)
        position.shares -= shares
        position.legs.append(ExitLeg(date=date, shares=shares, price=price, reason=reason))
        return proceeds

    # -- bookkeeping -------------------------------------------------------

    def _mark_to_market(self, cash, open_positions, prepared, date) -> float:
        equity = cash
        for symbol, position in open_positions.items():
            frame = prepared[symbol]
            if date in frame.index:
                equity += position.open_shares * float(frame.loc[date, "close"])
            else:
                equity += position.open_shares * position.entry_price
        return equity

    def _blotter_row(self, position: Position) -> dict:
        pnl = position.realised_pnl
        r_multiple = pnl / position.initial_risk_dollars if position.initial_risk_dollars else 0.0
        return {
            "symbol": position.symbol,
            "entry_date": position.entry_date,
            "exit_date": position.legs[-1].date if position.legs else position.entry_date,
            "entry_price": position.entry_price,
            "shares": position.initial_shares,
            "risk_per_share": position.risk_per_share,
            "pnl": pnl,
            "r_multiple": r_multiple,
            "scaled": position.scaled,
            "exit_reason": position.legs[-1].reason if position.legs else "none",
            "legs": len(position.legs),
        }


def run_config(cfg: StrategyConfig, universe, benchmarks, **kwargs):
    """Convenience wrapper: run one config and return (perf, curve, blotter)."""
    engine = Backtester(cfg, **kwargs)
    curve, blotter = engine.run(universe, benchmarks)
    perf = metrics.summarise(curve, blotter, exposure=engine.exposure)
    return perf, curve, blotter
