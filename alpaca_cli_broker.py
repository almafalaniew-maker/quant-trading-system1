"""Broker backed by Alpaca's official CLI instead of the Python SDK.

Alpaca ship a Go CLI built for exactly this - non-interactive, JSON out,
meaningful exit codes, automatic retry on 429/5xx. It is a single static binary,
so a deployment needs no Python broker dependency at all.

Two deliberate choices:

* Every call goes through `alpaca api <METHOD> <PATH>` rather than the
  convenience subcommands. The CLI is alpha and its own README warns that
  "commands, flags, and output formats may change or be removed without notice";
  the REST paths underneath are stable and documented. Driving the raw API
  surface means a CLI release cannot silently change what an order looks like.

* Every order carries a `client_order_id`. Alpaca rejects a duplicate with 409,
  which turns the dangerous case - a submission that times out after the order
  was accepted - from "resubmit and hope" into a question with a definite
  answer. The SDK path had no protection against that at all.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass

from position_manager import BrokerOrder

# Exit codes, from the CLI's documented contract.
EXIT_OK, EXIT_API_ERROR, EXIT_AUTH_ERROR = 0, 1, 2


class AlpacaCliError(RuntimeError):
    """A CLI invocation that failed, with the structured error it reported."""

    def __init__(self, argv: list[str], code: int, stderr: str):
        self.code, self.stderr = code, stderr
        self.status = 0          # the HTTP status the API returned, when it gave one
        detail = stderr.strip()
        try:
            payload = json.loads(stderr)
            detail = payload.get("error", detail)
            self.status = int(payload.get("status") or 0)
        except Exception:
            pass
        if code == EXIT_AUTH_ERROR:
            detail = (f"authentication failed ({detail}). Check ALPACA_API_KEY and "
                      f"ALPACA_SECRET_KEY - note the CLI uses ALPACA_SECRET_KEY, "
                      f"not ALPACA_API_SECRET.")
        super().__init__(f"alpaca {' '.join(argv)} -> exit {code}: {detail}")


@dataclass
class CliConfig:
    binary: str = "alpaca"
    timeout: int = 45
    live: bool = False          # maps to ALPACA_LIVE_TRADE; anything else is paper


class AlpacaCliBroker:
    """Implements both the entry and management broker surfaces via the CLI."""

    def __init__(self, config: CliConfig | None = None):
        self.cfg = config or CliConfig()
        if not shutil.which(self.cfg.binary):
            raise SystemExit(
                f"error: '{self.cfg.binary}' not found on PATH. Install it with\n"
                f"  go install github.com/alpacahq/cli/cmd/alpaca@latest\n"
                f"and make sure $GOPATH/bin is on your PATH.")

    # -- invocation --------------------------------------------------------

    def _run(self, method: str, path: str, body: dict | None = None):
        argv = [self.cfg.binary, "api", method, path, "--quiet"]
        # Always hand the child an explicit stdin, even when there is no body.
        # Passing None makes it inherit ours, and the CLI reads stdin for a
        # payload - under cron, a pipe, or a test harness that blocks forever
        # on input that never arrives. An empty string closes it immediately.
        proc = subprocess.run(
            argv,
            input=json.dumps(body) if body is not None else "",
            capture_output=True, text=True, timeout=self.cfg.timeout,
            env=self._env())
        if proc.returncode != EXIT_OK:
            raise AlpacaCliError(argv[1:], proc.returncode, proc.stderr)
        if not proc.stdout.strip():
            return None
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise AlpacaCliError(argv[1:], EXIT_API_ERROR,
                                 f"unparseable output: {proc.stdout[:200]}") from exc

    def _env(self) -> dict:
        import os
        env = dict(os.environ)
        env["ALPACA_QUIET"] = "1"
        # Only the literal string "true" opts into live; anything else is paper.
        env["ALPACA_LIVE_TRADE"] = "true" if self.cfg.live else "false"
        return env

    # -- account -----------------------------------------------------------

    def account(self) -> dict:
        return self._run("GET", "/v2/account")

    def equity(self) -> float:
        return float(self.account()["equity"])

    def clock(self):
        raw = self._run("GET", "/v2/clock")

        class _Clock:
            is_open = bool(raw.get("is_open"))
            next_open = raw.get("next_open")
            next_close = raw.get("next_close")

        return _Clock()

    # -- positions ---------------------------------------------------------

    def positions(self) -> dict[str, int]:
        return {p["symbol"]: int(float(p["qty"])) for p in self._run("GET", "/v2/positions")}

    def open_symbols(self) -> set[str]:
        return set(self.positions())

    # -- orders ------------------------------------------------------------

    def open_orders(self, symbol: str) -> list[BrokerOrder]:
        raw = self._run("GET", f"/v2/orders?status=open&symbols={symbol}") or []
        out = []
        for o in raw:
            price = o.get("stop_price") or o.get("limit_price")
            out.append(BrokerOrder(
                id=str(o["id"]), symbol=o["symbol"],
                kind="stop" if o.get("stop_price") else "limit",
                qty=int(float(o["qty"])), price=float(price) if price else 0.0))
        return out

    def cancel_order(self, order_id: str) -> None:
        try:
            self._run("DELETE", f"/v2/orders/{order_id}")
        except AlpacaCliError as exc:
            # An order that already filled or was already cancelled is not a
            # failure here - reconciliation wants it gone, and it is gone.
            # Match on the status the API reported, not on the wording of the
            # message, which is the vendor's to change.
            if exc.status not in (404, 422):
                raise

    def _submit(self, body: dict) -> str:
        body.setdefault("client_order_id", f"qts-{uuid.uuid4()}")
        try:
            return str(self._run("POST", "/v2/orders", body)["id"])
        except AlpacaCliError as exc:
            if exc.status == 409:
                # The order already exists under this id. Resubmitting would
                # double the position, so resolve it rather than retrying.
                existing = self._run(
                    "GET", f"/v2/orders:by_client_order_id?client_order_id="
                           f"{body['client_order_id']}")
                if existing:
                    return str(existing["id"])
            raise

    def submit_stop(self, symbol: str, qty: int, stop_price: float) -> str:
        return self._submit({"symbol": symbol, "qty": str(qty), "side": "sell",
                             "type": "stop", "time_in_force": "gtc",
                             "stop_price": f"{stop_price:.2f}"})

    def submit_market_sell(self, symbol: str, qty: int) -> str:
        return self._submit({"symbol": symbol, "qty": str(qty), "side": "sell",
                             "type": "market", "time_in_force": "day"})

    def submit_bracket(self, plan) -> str:
        """Entry, protective stop, and take-profit.

        Submitted as three orders because the exit can be split: a scale-out
        tranche and a trailed remainder have different targets. The stop covers
        the whole position from the moment the entry fills.
        """
        entry = self._submit({"symbol": plan.symbol, "qty": str(plan.shares),
                              "side": "buy", "type": "market", "time_in_force": "day"})
        self.submit_stop(plan.symbol, plan.shares, plan.stop_price)
        if plan.take_profit_shares > 0:
            self._submit({"symbol": plan.symbol, "qty": str(plan.take_profit_shares),
                          "side": "sell", "type": "limit", "time_in_force": "gtc",
                          "limit_price": f"{plan.take_profit_price:.2f}"})
        return entry
