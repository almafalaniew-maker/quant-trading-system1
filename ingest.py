"""Turn `get_equity_historicals` JSON into the CSV layout the backtester loads.

The connector's bars arrive as JSON in the agent's context; this script is the
one place they get written to disk, so the parsing and validation happen once
and identically for every batch.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

BARS_DIR = Path(__file__).parent / "bars"
COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def bars_to_frame(bars: list[dict]) -> pd.DataFrame:
    rows = [
        {
            "date": bar["begins_at"][:10],
            "open": float(bar["open_price"]),
            "high": float(bar["high_price"]),
            "low": float(bar["low_price"]),
            "close": float(bar["close_price"]),
            "volume": int(bar["volume"]),
        }
        for bar in bars
        if not bar.get("interpolated")          # gap-fill carries no information
    ]
    return pd.DataFrame(rows, columns=COLUMNS)


def validate(symbol: str, frame: pd.DataFrame) -> list[str]:
    """Catch a corrupt batch before it silently poisons a backtest."""
    problems = []
    if frame.empty:
        return [f"{symbol}: empty"]
    if frame["date"].duplicated().any():
        problems.append(f"{symbol}: duplicate dates")
    if not frame["date"].is_monotonic_increasing:
        problems.append(f"{symbol}: dates out of order")
    body_high = frame[["open", "close"]].max(axis=1)
    body_low = frame[["open", "close"]].min(axis=1)
    if (frame["high"] < body_high - 1e-6).any():
        problems.append(f"{symbol}: high below open/close")
    if (frame["low"] > body_low + 1e-6).any():
        problems.append(f"{symbol}: low above open/close")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        problems.append(f"{symbol}: non-positive price")
    if (frame["volume"] < 0).any():
        problems.append(f"{symbol}: negative volume")
    return problems


def ingest(payload: dict) -> None:
    """Merge one connector response into bars/<SYMBOL>.csv, de-duplicating dates."""
    BARS_DIR.mkdir(exist_ok=True)
    for result in payload["data"]["results"]:
        symbol = result["symbol"].upper()
        incoming = bars_to_frame(result["bars"])
        path = BARS_DIR / f"{symbol}.csv"

        if path.exists():
            existing = pd.read_csv(path, dtype={"date": str})
            merged = pd.concat([existing, incoming], ignore_index=True)
        else:
            merged = incoming

        merged = (merged.drop_duplicates(subset="date", keep="last")
                        .sort_values("date")
                        .reset_index(drop=True))
        problems = validate(symbol, merged)
        if problems:
            print("  !! " + "; ".join(problems), file=sys.stderr)
        merged.to_csv(path, index=False)
        print(f"  {symbol}: +{len(incoming)} -> {len(merged)} bars "
              f"({merged['date'].iloc[0]} to {merged['date'].iloc[-1]})")


def status() -> None:
    """Print what has been ingested so far."""
    files = sorted(BARS_DIR.glob("*.csv"))
    if not files:
        print("no bars ingested yet")
        return
    rows = []
    for path in files:
        frame = pd.read_csv(path, dtype={"date": str})
        rows.append({"symbol": path.stem, "bars": len(frame),
                     "start": frame["date"].iloc[0], "end": frame["date"].iloc[-1]})
    table = pd.DataFrame(rows)
    print(table.to_string(index=False))
    print(f"\n{len(table)} symbols, {table['bars'].sum():,} bars total")




# ---------------------------------------------------------------------------
# Batch sync
# ---------------------------------------------------------------------------

TOOL_RESULTS = Path(
    "/root/.claude/projects/-home-user-quant-trading-system1/"
    "374aa6ea-2c44-560c-8f18-e3a1adbf6f6e/tool-results"
)
LEDGER = BARS_DIR / ".ingested"


def sync() -> None:
    """Ingest every connector payload not yet folded into bars/.

    Large responses are spilled to disk by the harness rather than returned
    inline, so the bars are read straight from those files - no retyping of
    price data, and therefore no chance of a transcription error reaching a
    backtest.
    """
    seen = set(LEDGER.read_text().split()) if LEDGER.exists() else set()
    files = sorted(TOOL_RESULTS.glob("mcp-trading-get_equity_historicals-*.txt"))
    fresh = [f for f in files if f.name not in seen]
    if not fresh:
        print("nothing new to ingest")
        return

    for path in fresh:
        print(f"[{path.name}]")
        try:
            ingest(json.loads(path.read_text()))
        except Exception as exc:
            print(f"  !! skipped: {exc}", file=sys.stderr)
            continue
        seen.add(path.name)

    LEDGER.write_text("\n".join(sorted(seen)))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "stdin"
    if command == "status":
        status()
    elif command == "sync":
        sync()
    else:
        ingest(json.load(sys.stdin))
