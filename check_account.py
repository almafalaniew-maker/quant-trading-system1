"""Print the account the strategy would trade, and sanity-check it against the
sizing assumptions. Run this first on any machine you intend to deploy to.

    export ALPACA_API_KEY=...  ALPACA_API_SECRET=...
    python3 check_account.py

Uses only the standard library, so it works before anything is pip-installed.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

PAPER = "https://paper-api.alpaca.markets"
LIVE = "https://api.alpaca.markets"


def get(base: str, path: str, key: str, secret: str) -> dict:
    req = urllib.request.Request(
        f"{base}{path}",
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main() -> int:
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_API_SECRET")
    if not key or not secret:
        print("error: set ALPACA_API_KEY and ALPACA_API_SECRET first", file=sys.stderr)
        return 2

    base = LIVE if os.getenv("QTS_REAL_MONEY") else PAPER
    print(f"endpoint: {base}" + ("   *** REAL MONEY ***" if base == LIVE else "   (paper)"))
    try:
        acct = get(base, "/v2/account", key, secret)
    except urllib.error.HTTPError as e:
        print(f"error: HTTP {e.code} - {e.reason}", file=sys.stderr)
        print("  401/403 means the key pair is wrong, or it is a live key on the "
              "paper endpoint (or vice versa).", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: could not reach Alpaca - {e}", file=sys.stderr)
        return 1

    equity = float(acct["equity"])
    print(f"\n  status          {acct['status']}")
    print(f"  equity          ${equity:,.2f}")
    print(f"  cash            ${float(acct['cash']):,.2f}")
    print(f"  BUYING POWER    ${float(acct['buying_power']):,.2f}")
    print(f"  portfolio value ${float(acct['portfolio_value']):,.2f}")
    for flag in ("trading_blocked", "account_blocked", "transfers_blocked"):
        if acct.get(flag):
            print(f"  !! {flag} is TRUE - the strategy cannot trade")

    positions = get(base, "/v2/positions", key, secret)
    print(f"\n  open positions  {len(positions)}")
    for p in positions[:15]:
        print(f"    {p['symbol']:<6} {p['qty']:>8} @ ${float(p['avg_entry_price']):>10,.2f}"
              f"   P/L ${float(p['unrealized_pl']):>+10,.2f}")

    # --- does the account fit what the backtests assumed? -----------------
    print("\n  against the strategy's sizing (1% risk, 15 slots):")
    print(f"    risk per trade      ${equity * 0.01:,.2f}")
    print(f"    typical position    ~${equity * 0.07:,.2f} (a ~14% stop distance)")
    if equity < 25_000:
        print("    !! Under $25,000 many positions round to very few shares, so the")
        print("       risk budget stops being met and results drift from the backtest.")
        print("    !! Also note the US pattern-day-trader rule applies under $25,000.")
    elif equity < 100_000:
        print("    ok, though smaller accounts see more rounding drag than the "
              "$100,000 the backtests assumed.")
    else:
        print("    ok - at or above the $100,000 the backtests assumed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
