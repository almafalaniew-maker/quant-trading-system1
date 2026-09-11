#!/usr/bin/env python3
"""A fake `alpaca` CLI, so the broker can be tested without a network or keys.

Reads STUB_LOG (where to record calls) and STUB_MODE (which failure to simulate)
from the environment, and answers the handful of REST paths the broker uses.
"""
import json
import os
import sys

argv = sys.argv[1:]                      # api <METHOD> <PATH> --quiet
method, path = argv[1], argv[2]
body = "" if sys.stdin.isatty() else sys.stdin.read()

with open(os.environ["STUB_LOG"], "a") as log:
    log.write(json.dumps({"method": method, "path": path, "body": body,
                          "live": os.environ.get("ALPACA_LIVE_TRADE")}) + "\n")

mode = os.environ.get("STUB_MODE", "")

if mode == "auth":
    sys.stderr.write(json.dumps({"error": "unauthorized", "status": 401}))
    sys.exit(2)

if path == "/v2/account":
    print(json.dumps({"equity": "150000.50", "cash": "90000", "status": "ACTIVE"}))
elif path == "/v2/positions":
    print(json.dumps([{"symbol": "NVDA", "qty": "55", "avg_entry_price": "180"},
                      {"symbol": "MU", "qty": "20", "avg_entry_price": "400"}]))
elif path == "/v2/clock":
    print(json.dumps({"is_open": True, "next_close": "2026-09-11T20:00:00Z"}))
elif path.startswith("/v2/orders:by_client_order_id"):
    print(json.dumps({"id": "already-there"}))
elif path.startswith("/v2/orders?"):
    print(json.dumps([
        {"id": "o1", "symbol": "NVDA", "qty": "55", "stop_price": "171.00"},
        {"id": "o2", "symbol": "NVDA", "qty": "55", "limit_price": "252.00"}]))
elif method == "POST" and path == "/v2/orders":
    if mode == "duplicate":
        sys.stderr.write(json.dumps({"error": "duplicate client_order_id", "status": 409}))
        sys.exit(1)
    print(json.dumps({"id": "new-order-1"}))
elif method == "DELETE":
    if mode == "gone":
        sys.stderr.write(json.dumps({"error": "order not found", "status": 404}))
        sys.exit(1)
    print("")
else:
    sys.stderr.write(json.dumps({"error": f"stub has no route for {method} {path}"}))
    sys.exit(1)
