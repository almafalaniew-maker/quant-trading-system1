#!/usr/bin/env bash
# One-command setup for the trading system.
#
#   ./setup.sh            verify an existing install
#   ./setup.sh --install  install dependencies, seed data, then verify
#
# Credentials come from .env (see .env.example). This script never contains
# them, because it is committed to a repository and they must not be.
set -euo pipefail

cd "$(dirname "$0")"
BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; RED=$'\033[31m'; OFF=$'\033[0m'
step(){ printf "\n%s==> %s%s\n" "$BOLD" "$1" "$OFF"; }
ok(){   printf "  %s✓%s %s\n" "$GREEN" "$OFF" "$1"; }
bad(){  printf "  %s✗%s %s\n" "$RED" "$OFF" "$1"; }
die(){  bad "$1"; exit 1; }

INSTALL=0
[ "${1:-}" = "--install" ] && INSTALL=1

step "Checking prerequisites"
command -v python3 >/dev/null || die "python3 not found. Install Python 3.11 or newer."
PYV=$(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ok "python3 $PYV"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' \
  || die "Python 3.11+ required, found $PYV"

step "Loading credentials"
[ -f .env ] || die ".env not found. Copy .env.example to .env and fill in your keys."
PERMS=$(stat -c '%a' .env 2>/dev/null || stat -f '%A' .env 2>/dev/null || echo "")
if [ "$PERMS" != "600" ]; then
  chmod 600 .env && ok "tightened .env permissions to 600"
fi
set -a; . ./.env; set +a
[ -n "${ALPACA_API_KEY:-}" ] || die "ALPACA_API_KEY is not set in .env"
[ -n "${ALPACA_API_SECRET:-}${ALPACA_SECRET_KEY:-}" ] || die "the secret key is not set in .env"
# The Python SDK reads ALPACA_API_SECRET; Alpaca's CLI reads ALPACA_SECRET_KEY.
# Mirror whichever was provided so both work.
export ALPACA_API_SECRET="${ALPACA_API_SECRET:-${ALPACA_SECRET_KEY:-}}"
export ALPACA_SECRET_KEY="${ALPACA_SECRET_KEY:-${ALPACA_API_SECRET:-}}"
ok "key ${ALPACA_API_KEY:0:6}… loaded"
if [ "${QTS_REAL_MONEY:-}" = "" ]; then ok "mode: PAPER"; else bad "mode: REAL MONEY"; fi

if [ "$INSTALL" = "1" ]; then
  step "Installing Python packages"
  python3 -m pip install --quiet --upgrade pip
  python3 -m pip install --quiet -r requirements.txt
  ok "pandas, numpy"
fi

step "Running self-tests"
if python3 test_system.py >/tmp/qts-tests.log 2>&1; then
  ok "$(grep -c '\[PASS\]' /tmp/qts-tests.log) checks passed"
else
  bad "self-tests failed — see /tmp/qts-tests.log"; exit 1
fi

step "Checking the Alpaca account"
python3 check_account.py || die "could not reach Alpaca. Check the keys and this machine's internet."

if [ "$INSTALL" = "1" ]; then
  step "Downloading price history"
  if [ -d bars ] && [ -n "$(ls -A bars 2>/dev/null)" ]; then
    python3 fetch_bars.py --symbols-from bars/
  else
    python3 fetch_bars.py --start 2020-01-01 --symbols \
      AAPL,MSFT,NVDA,AMZN,META,GOOGL,AVGO,AMD,CRM,ADBE,NFLX,TSLA,MU,QCOM,LRCX,ON,\
PLTR,SHOP,NOW,SNOW,CRWD,DDOG,NET,ANET,UBER,ABNB,COIN,XOM,CAT,DE,JPM,GS,LLY,UNH,\
COST,WMT,HD,FCX,SLB,MRNA
  fi
  ok "price history ready"
fi

step "Ready"
cat <<'NEXT'
  Next, in order — do not skip ahead:

  1. See what it would buy today, without touching the account:
       python3 run_session.py --data ./bars

  2. When that looks right, trade it on paper for several weeks:
       QTS_ALLOW_LIVE=yes python3 run_session.py --data ./bars --live

  3. Once it has been boring for weeks, schedule it:
       sudo cp deploy/qts-session.* /etc/systemd/system/
       sudo systemctl enable --now qts-session.timer

  Stop everything at any time:
       echo stop > HALT

  Full runbook: DEPLOYMENT.md
NEXT
