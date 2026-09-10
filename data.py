"""Data loading for the backtester.

Three sources, all returning the same shape: a dict of symbol -> DataFrame with
a DatetimeIndex and columns open/high/low/close/volume.

* `load_csv_dir`  - the production path. Point it at a directory of daily bars.
* `load_yfinance` - convenience for a local machine with internet access.
* `synthetic_universe` - deterministic fake bars used only to exercise the
  engine's mechanics in tests. It carries no information about whether the
  strategy has an edge, and results from it must never be quoted as performance.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case the columns, sort by date, and keep only what the engine needs."""
    df = df.rename(columns={c: c.lower().replace(" ", "_") for c in df.columns})
    if "date" in df.columns:
        df = df.set_index(pd.to_datetime(df["date"]))
    df.index = pd.to_datetime(df.index)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns {missing}; got {list(df.columns)}")
    return df[REQUIRED_COLUMNS].sort_index()


def load_csv_dir(directory: str | Path, symbols: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Load `<SYMBOL>.csv` files of daily bars from a directory."""
    directory = Path(directory)
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(directory.glob("*.csv")):
        symbol = path.stem.upper()
        if symbols and symbol not in symbols:
            continue
        frames[symbol] = _normalise(pd.read_csv(path))
    if not frames:
        raise FileNotFoundError(f"no CSV bars found in {directory}")
    return frames


def load_yfinance(symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """Download daily bars via yfinance.

    Kept out of the default path on purpose: this session's network policy blocks
    Yahoo, and a backtest that silently downloads on import is a backtest nobody
    can reproduce. Install yfinance and call this explicitly where the data is
    reachable.
    """
    import yfinance as yf  # imported lazily so the engine has no hard dependency

    raw = yf.download(symbols, start=start, end=end, auto_adjust=True, progress=False,
                      group_by="ticker")
    frames: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        # yfinance returns a flat frame for one symbol and a MultiIndex for many.
        block = raw[symbol] if isinstance(raw.columns, pd.MultiIndex) else raw
        block = block.dropna(how="all")
        if block.empty:
            continue
        frames[symbol] = _normalise(block)
    return frames


def _bars_from_closes(closes: np.ndarray, rng: np.random.Generator,
                      index: pd.DatetimeIndex, gap_days: np.ndarray) -> pd.DataFrame:
    """Turn a close series into plausible OHLCV bars, with gaps where flagged."""
    n = len(closes)
    opens = np.empty(n)
    opens[0] = closes[0]
    prior = closes[:-1]
    drift = rng.normal(0.0, 0.006, n - 1)
    opens[1:] = prior * (1.0 + drift + gap_days[1:] * rng.uniform(0.03, 0.09, n - 1))

    span = np.abs(closes - opens) + closes * rng.uniform(0.004, 0.02, n)
    highs = np.maximum(opens, closes) + span * rng.uniform(0.1, 0.6, n)
    lows = np.minimum(opens, closes) - span * rng.uniform(0.1, 0.6, n)
    lows = np.maximum(lows, 0.01)
    volume = rng.uniform(1.2e6, 6e6, n) * (1.0 + 2.0 * gap_days)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volume},
        index=index,
    )


def synthetic_universe(
    n_symbols: int = 40,
    days: int = 1500,
    seed: int = 7,
    start: str = "2015-01-02",
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """Deterministic fake market: a few trending names, a bear stretch, and gaps.

    Returns (universe, benchmarks). Mechanics only - see the module docstring.
    """
    rng = np.random.default_rng(seed)
    index = pd.bdate_range(start=start, periods=days)

    # A market factor with a deliberate bear phase in the middle third.
    phase = np.ones(days)
    phase[int(days * 0.45): int(days * 0.60)] = -1.6
    market_ret = rng.normal(0.0004, 0.010, days) * phase
    market = 400.0 * np.exp(np.cumsum(market_ret))

    benchmarks = {}
    for ticker, beta in (("SPY", 1.0), ("QQQ", 1.25)):
        closes = market ** 1.0 if beta == 1.0 else 300.0 * np.exp(np.cumsum(market_ret * beta))
        benchmarks[ticker] = _bars_from_closes(
            np.asarray(closes, dtype=float), rng, index, np.zeros(days)
        )

    universe: dict[str, pd.DataFrame] = {}
    for i in range(n_symbols):
        symbol = f"SYM{i:03d}"
        beta = rng.uniform(0.6, 2.0)
        idio = rng.normal(0.0, rng.uniform(0.012, 0.030), days)
        # A minority of names get a genuine multi-month trend, as in a real market.
        trend = rng.normal(0.0012, 0.0004) if rng.random() < 0.25 else -0.0002
        gaps = (rng.random(days) < 0.02).astype(float)
        rets = beta * market_ret + idio + trend + gaps * rng.uniform(0.0, 0.02, days)
        closes = rng.uniform(8.0, 90.0) * np.exp(np.cumsum(rets))
        universe[symbol] = _bars_from_closes(closes, rng, index, gaps)

    return universe, benchmarks
