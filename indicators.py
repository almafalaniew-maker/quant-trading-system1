"""Vectorised indicator helpers shared by the backtester and the live executor.

Every function takes and returns pandas objects aligned on the input index, and
uses only information available up to each bar (no forward fill from the future).
"""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average, seeded the same way charting packages do."""
    return series.ewm(span=span, adjust=False).mean()


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Classic true range: the widest of today's range and the two gap ranges."""
    prev_close = close.shift(1)
    ranges = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Average true range using Wilder's smoothing."""
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def rolling_high(high: pd.Series, window: int) -> pd.Series:
    """Highest high over the `window` bars *ending on the previous bar*.

    Shifted by one so a breakout test never compares today's high against itself.
    """
    return high.rolling(window=window, min_periods=window).max().shift(1)


def average_dollar_volume(close: pd.Series, volume: pd.Series, window: int) -> pd.Series:
    """Rolling average dollar volume - a better liquidity gate than share count.

    A 500k-share filter lets a $5 stock through on $2.5m of flow while blocking a
    $400 stock trading $150m; dollars are what a position actually has to absorb.
    """
    return (close * volume).rolling(window=window, min_periods=window).mean()


def average_volume(volume: pd.Series, window: int) -> pd.Series:
    """Rolling average share volume, kept for parity with share-count filters."""
    return volume.rolling(window=window, min_periods=window).mean()
