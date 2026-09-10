"""Performance statistics computed from an equity curve and a trade blotter."""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass
class Performance:
    trades: int
    win_rate: float
    total_return: float
    cagr: float
    max_drawdown: float
    profit_factor: float
    expectancy_r: float
    avg_win_r: float
    avg_loss_r: float
    largest_win_r: float
    sharpe: float
    exposure: float

    def as_dict(self) -> dict:
        return asdict(self)


def max_drawdown(equity: pd.Series) -> float:
    """Largest peak-to-trough decline of the equity curve, as a positive fraction."""
    if equity.empty:
        return 0.0
    running_peak = equity.cummax()
    return float((1.0 - equity / running_peak).max())


def cagr(equity: pd.Series) -> float:
    """Annualised compound growth rate over the curve's actual calendar span."""
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    days = (equity.index[-1] - equity.index[0]).days
    if days <= 0:
        return 0.0
    years = days / 365.25
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)


def sharpe(equity: pd.Series, risk_free: float = 0.0) -> float:
    """Annualised Sharpe from daily equity returns."""
    returns = equity.pct_change().dropna()
    if returns.empty or returns.std() == 0:
        return 0.0
    excess = returns - risk_free / TRADING_DAYS
    return float(np.sqrt(TRADING_DAYS) * excess.mean() / returns.std())


def summarise(equity: pd.Series, trades: pd.DataFrame, exposure: float = 0.0) -> Performance:
    """Roll an equity curve and blotter up into the headline numbers."""
    if trades.empty:
        return Performance(
            trades=0, win_rate=0.0,
            total_return=float(equity.iloc[-1] / equity.iloc[0] - 1.0) if len(equity) > 1 else 0.0,
            cagr=cagr(equity), max_drawdown=max_drawdown(equity),
            profit_factor=0.0, expectancy_r=0.0, avg_win_r=0.0, avg_loss_r=0.0,
            largest_win_r=0.0, sharpe=sharpe(equity), exposure=exposure,
        )

    r = trades["r_multiple"]
    wins, losses = r[r > 0], r[r <= 0]
    gross_win = float(trades.loc[r > 0, "pnl"].sum())
    gross_loss = float(-trades.loc[r <= 0, "pnl"].sum())

    return Performance(
        trades=int(len(trades)),
        win_rate=float(len(wins) / len(r)),
        total_return=float(equity.iloc[-1] / equity.iloc[0] - 1.0),
        cagr=cagr(equity),
        max_drawdown=max_drawdown(equity),
        profit_factor=float(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        expectancy_r=float(r.mean()),
        avg_win_r=float(wins.mean()) if len(wins) else 0.0,
        avg_loss_r=float(losses.mean()) if len(losses) else 0.0,
        largest_win_r=float(r.max()),
        sharpe=sharpe(equity),
        exposure=exposure,
    )


def yearly_returns(equity: pd.Series) -> pd.Series:
    """Calendar-year returns of the equity curve."""
    if equity.empty:
        return pd.Series(dtype=float)
    year_end = equity.resample("YE").last()
    start = pd.Series([equity.iloc[0]], index=[year_end.index[0]])
    prior = pd.concat([start, year_end.iloc[:-1].set_axis(year_end.index[1:])])
    out = (year_end / prior - 1.0)
    out.index = out.index.year
    return out
