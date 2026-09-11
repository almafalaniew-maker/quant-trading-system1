"""Refresh bars/ from Alpaca's market data API.

The backtests ran on a static directory of CSVs. A scheduled system needs that
directory to be current before every session, or it trades yesterday's breakouts.

This uses Alpaca's data API with the same key pair as trading, so there is no
second vendor to sign up for. It is incremental: only bars newer than what is
already on disk are requested, which keeps a daily refresh cheap and makes a
re-run after a failure safe.

    python3 fetch_bars.py --symbols-from bars/          # refresh what exists
    python3 fetch_bars.py --symbols AAPL,MSFT --start 2021-01-01

Note that Alpaca's free data tier serves IEX rather than full-market
consolidated prices. For daily bars the difference is small but it is not zero,
and it is not what the backtests were computed on - those used consolidated
split-adjusted bars. Expect live fills and signals to differ slightly from any
backtest re-run on this data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

import pandas as pd

BARS_DIR = Path("bars")
COLUMNS = ["date", "open", "high", "low", "close", "volume"]
# Enough history for a 50-day trend filter plus a 20-day liquidity window,
# with room to spare for holidays.
WARMUP_DAYS = 160


def data_client(key: str | None = None, secret: str | None = None):
    from alpaca.data.historical import StockHistoricalDataClient
    key = key or os.getenv("ALPACA_API_KEY")
    secret = secret or os.getenv("ALPACA_API_SECRET")
    if not key or not secret:
        raise SystemExit("error: ALPACA_API_KEY and ALPACA_API_SECRET must be set")
    return StockHistoricalDataClient(key, secret)


def to_frame(bars) -> pd.DataFrame:
    """Normalise an Alpaca bar set into the engine's CSV layout."""
    rows = [{"date": b.timestamp.date().isoformat(), "open": float(b.open),
             "high": float(b.high), "low": float(b.low), "close": float(b.close),
             "volume": int(b.volume)} for b in bars]
    return pd.DataFrame(rows, columns=COLUMNS)


def merge(existing: pd.DataFrame | None, incoming: pd.DataFrame) -> pd.DataFrame:
    """Union on date, newest wins - so a re-run repairs a partial write."""
    frame = incoming if existing is None else pd.concat([existing, incoming],
                                                        ignore_index=True)
    return (frame.drop_duplicates(subset="date", keep="last")
                 .sort_values("date").reset_index(drop=True))


def validate(symbol: str, frame: pd.DataFrame) -> list[str]:
    """Refuse to write bars the backtester would fill against impossibly.

    The same invariants data.py enforces at load time, applied here so a bad
    vendor response is caught at the boundary rather than days later.
    """
    problems = []
    if frame.empty:
        return [f"{symbol}: empty"]
    if frame["date"].duplicated().any():
        problems.append("duplicate dates")
    if not frame["date"].is_monotonic_increasing:
        problems.append("dates out of order")
    body_hi = frame[["open", "close"]].max(axis=1)
    body_lo = frame[["open", "close"]].min(axis=1)
    if (frame["high"] < body_hi - 1e-6).any():
        problems.append("high below open/close")
    if (frame["low"] > body_lo + 1e-6).any():
        problems.append("low above open/close")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        problems.append("non-positive price")
    return [f"{symbol}: {p}" for p in problems]


def last_date(path: Path) -> str | None:
    if not path.exists():
        return None
    frame = pd.read_csv(path, dtype={"date": str})
    return frame["date"].iloc[-1] if len(frame) else None


def refresh(symbols: list[str], client, bars_dir: Path = BARS_DIR,
            start: str | None = None, end: str | None = None) -> dict[str, int]:
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    bars_dir.mkdir(exist_ok=True)
    added: dict[str, int] = {}
    today = dt.date.today()

    for symbol in symbols:
        path = bars_dir / f"{symbol}.csv"
        if start:
            begin = dt.date.fromisoformat(start)
        else:
            seen = last_date(path)
            begin = (dt.date.fromisoformat(seen) - dt.timedelta(days=5) if seen
                     else today - dt.timedelta(days=WARMUP_DAYS * 2))
        try:
            response = client.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=symbol, timeframe=TimeFrame.Day,
                start=begin, end=dt.date.fromisoformat(end) if end else None,
                adjustment="split"))
        except Exception as exc:                 # one bad symbol must not stop the rest
            print(f"  !! {symbol}: {exc}", file=sys.stderr)
            continue

        series = response.data.get(symbol, [])
        if not series:
            print(f"  -- {symbol}: no new bars")
            continue

        incoming = to_frame(series)
        existing = pd.read_csv(path, dtype={"date": str}) if path.exists() else None
        merged = merge(existing, incoming)
        problems = validate(symbol, merged)
        if problems:
            print(f"  !! {'; '.join(problems)} - not written", file=sys.stderr)
            continue

        before = 0 if existing is None else len(existing)
        merged.to_csv(path, index=False)
        added[symbol] = len(merged) - before
        print(f"  {symbol}: +{added[symbol]} -> {len(merged)} bars "
              f"(through {merged['date'].iloc[-1]})")
    return added


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--symbols", help="comma-separated list")
    group.add_argument("--symbols-from", help="directory of existing <SYMBOL>.csv files")
    parser.add_argument("--bars-dir", default=str(BARS_DIR))
    parser.add_argument("--start", help="ISO date; default is incremental")
    parser.add_argument("--end", help="ISO date; default is today")
    args = parser.parse_args(argv)

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = sorted(p.stem.upper() for p in Path(args.symbols_from).glob("*.csv"))
    if not symbols:
        print("error: no symbols to fetch", file=sys.stderr)
        return 2

    # SPY drives the regime gate; QQQ is needed by the strict variant.
    for required in ("SPY", "QQQ"):
        if required not in symbols:
            symbols.append(required)

    print(f"refreshing {len(symbols)} symbols from Alpaca...")
    added = refresh(symbols, data_client(), Path(args.bars_dir), args.start, args.end)
    print(f"done: {sum(added.values()):,} new bars across {len(added)} symbols")
    return 0 if added else 1


if __name__ == "__main__":
    raise SystemExit(main())
