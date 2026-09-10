"""Breakout strategy: configuration, entry signals, regime gate and risk sizing.

Every idea worth A/B-testing is a field on `StrategyConfig`, so a variant is a
config object rather than a forked copy of the code. The defaults describe the
baseline system; `ab_test.py` flips one field at a time against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

import pandas as pd

import indicators as ind

GapMode = Literal["ignored", "required", "bonus"]
StopMode = Literal["atr", "fixed_pct"]
ExitMode = Literal["fixed_target", "scale_out"]
RegimeMode = Literal["none", "spy_sma", "dual_index_strict"]


@dataclass(frozen=True)
class StrategyConfig:
    """One complete parameterisation of the system."""

    name: str = "baseline"

    # --- Universe filters -------------------------------------------------
    min_price: float = 5.00
    min_dollar_volume: float = 5_000_000.0
    liquidity_window: int = 20

    # --- Entry: range breakout -------------------------------------------
    breakout_window: int = 5          # must clear the high of the last N bars
    require_prior_day_high: bool = True
    require_trend: bool = True        # close above its own 50-day SMA
    trend_window: int = 50

    # --- Entry: gap requirement (extracted from the gap-and-go script) ----
    # "ignored"  - a breakout needs no gap (baseline)
    # "required" - the open must gap up at least `min_gap_pct` over prior close
    # "bonus"    - no hard gate, but gappers are ranked first when slots are scarce
    gap_mode: GapMode = "ignored"
    min_gap_pct: float = 0.025

    # --- Regime gate ------------------------------------------------------
    # "spy_sma"            - SPY above its 50-day SMA (baseline)
    # "dual_index_strict"  - SPY *and* QQQ above both 50-SMA and 10-EMA
    regime_mode: RegimeMode = "spy_sma"
    regime_sma_window: int = 50
    regime_ema_span: int = 10

    # --- Risk sizing ------------------------------------------------------
    risk_pct: float = 0.005           # fraction of equity risked per trade
    stop_mode: StopMode = "atr"
    atr_window: int = 14
    atr_stop_mult: float = 2.0
    fixed_stop_pct: float = 0.02      # only used when stop_mode == "fixed_pct"
    max_position_pct: float = 0.20    # cap on notional per position
    max_open_positions: int = 10

    # --- Exits ------------------------------------------------------------
    exit_mode: ExitMode = "fixed_target"
    target_r: float = 4.0             # fixed_target: exit everything here
    scale_r: float = 2.0              # scale_out: first tranche here
    scale_fraction: float = 1.0 / 3.0 # scale_out: fraction sold at scale_r
    trail_atr_mult: float = 3.0       # scale_out: chandelier trail on the runner
    breakeven_after_scale: bool = True
    max_hold_days: int = 120

    def variant(self, name: str, **overrides) -> "StrategyConfig":
        """Return a copy with `overrides` applied - used to build A/B arms."""
        return replace(self, name=name, **overrides)


# ---------------------------------------------------------------------------
# Regime gate
# ---------------------------------------------------------------------------

def regime_series(
    benchmarks: dict[str, pd.DataFrame], cfg: StrategyConfig
) -> pd.Series:
    """Boolean series: is the broad market permissive on each date?

    `dual_index_strict` is the rule lifted from the gap-and-go script - both SPY
    and QQQ above their 50-SMA *and* their 10-EMA. The 10-EMA is the part that
    actually changes behaviour: it pulls the system out days-to-weeks earlier
    than the 50-SMA alone at the start of a rollover, at the cost of whipsawing
    out of shallow dips that the 50-SMA would have ridden through.
    """
    spy = benchmarks["SPY"]
    if cfg.regime_mode == "none":
        return pd.Series(True, index=spy.index)

    if cfg.regime_mode == "spy_sma":
        close = spy["close"]
        return (close > ind.sma(close, cfg.regime_sma_window)).fillna(False)

    if cfg.regime_mode == "dual_index_strict":
        ok = pd.Series(True, index=spy.index)
        for ticker in ("SPY", "QQQ"):
            frame = benchmarks.get(ticker)
            if frame is None:
                raise KeyError(f"dual_index_strict regime needs {ticker} data")
            close = frame["close"].reindex(spy.index).ffill()
            above_sma = close > ind.sma(close, cfg.regime_sma_window)
            above_ema = close > ind.ema(close, cfg.regime_ema_span)
            ok &= (above_sma & above_ema).fillna(False)
        return ok

    raise ValueError(f"unknown regime_mode {cfg.regime_mode!r}")


# ---------------------------------------------------------------------------
# Per-symbol signal preparation
# ---------------------------------------------------------------------------

def prepare_symbol(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    """Attach indicator and signal columns to one symbol's OHLCV frame.

    The returned `signal` column is True on bars where an entry would be taken
    at that bar's close. Every input to it is known by that close.
    """
    out = df.copy()
    close, high, low, volume = out["close"], out["high"], out["low"], out["volume"]
    open_ = out["open"]

    out["atr"] = ind.atr(high, low, close, cfg.atr_window)
    out["adv_dollars"] = ind.average_dollar_volume(close, volume, cfg.liquidity_window)
    out["prior_close"] = close.shift(1)
    out["prior_high"] = high.shift(1)
    out["range_high"] = ind.rolling_high(high, cfg.breakout_window)
    out["trend_sma"] = ind.sma(close, cfg.trend_window)
    out["gap_pct"] = (open_ / out["prior_close"]) - 1.0

    liquid = (close >= cfg.min_price) & (out["adv_dollars"] >= cfg.min_dollar_volume)

    breakout = close > out["range_high"]
    if cfg.require_prior_day_high:
        breakout &= close > out["prior_high"]

    trend_ok = pd.Series(True, index=out.index)
    if cfg.require_trend:
        trend_ok = close > out["trend_sma"]

    gap_ok = pd.Series(True, index=out.index)
    if cfg.gap_mode == "required":
        gap_ok = out["gap_pct"] >= cfg.min_gap_pct

    # A stop needs a positive distance or sizing blows up.
    out["stop_distance"] = stop_distance(out, cfg)
    sizable = out["stop_distance"] > 0

    out["signal"] = (liquid & breakout & trend_ok & gap_ok & sizable).fillna(False)
    out["is_gapper"] = (out["gap_pct"] >= cfg.min_gap_pct).fillna(False)
    return out


def stop_distance(frame: pd.DataFrame, cfg: StrategyConfig) -> pd.Series:
    """Per-share risk at entry - the definition of 1R for the trade.

    ATR mode scales the stop to how much the stock actually moves; a flat
    percentage puts the same stop on a 2%-a-day utility and a 9%-a-day biotech,
    so the biotech is stopped out by noise and the utility risks far more than 1R
    per unit of real adverse move.
    """
    if cfg.stop_mode == "atr":
        return frame["atr"] * cfg.atr_stop_mult
    if cfg.stop_mode == "fixed_pct":
        return frame["close"] * cfg.fixed_stop_pct
    raise ValueError(f"unknown stop_mode {cfg.stop_mode!r}")


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------

@dataclass
class Sizing:
    shares: int
    stop_price: float
    risk_per_share: float
    risk_dollars: float
    notional: float


def size_position(
    equity: float, entry_price: float, risk_per_share: float, cfg: StrategyConfig
) -> Sizing | None:
    """Convert an entry and a stop into a share count.

    Risk budget is the input and share count the output - never the reverse.
    The notional cap keeps a very tight stop from turning 0.5% of risk into an
    outsized slice of the book.
    """
    if risk_per_share <= 0 or entry_price <= 0 or equity <= 0:
        return None

    risk_dollars = equity * cfg.risk_pct
    shares = int(risk_dollars // risk_per_share)

    max_shares_by_notional = int((equity * cfg.max_position_pct) // entry_price)
    shares = min(shares, max_shares_by_notional)
    if shares <= 0:
        return None

    return Sizing(
        shares=shares,
        stop_price=entry_price - risk_per_share,
        risk_per_share=risk_per_share,
        risk_dollars=shares * risk_per_share,
        notional=shares * entry_price,
    )
