# Deploying this to a live Alpaca account

## Read this first

**This cannot run inside a Claude Code session.** That container is ephemeral and
its network policy blocks `paper-api.alpaca.markets` and `data.alpaca.markets`
outright (403 at the proxy, before TLS). Deployment has to happen on a machine
you control that stays on: a laptop that never sleeps, a VPS, a small cloud VM.

**The Alpaca code path has never been executed.** Every API surface it uses was
verified to exist in `alpaca-py` 0.44.0, and the order construction is unit
tested, but no order has ever been sent — not even on paper. Treat the first
live-ish run as a test of this code, not of the strategy.

**"24/7" is the wrong shape for this strategy.** It decides once per trading day
on completed daily bars. Running it continuously would not make it trade more; it
would make it act on unfinished bars, which is not what any backtest measured.
The schedule below runs it once per weekday after the close. That *is* the
strategy running automatically.

## What you need

- A host that is up at 16:30 America/New_York on weekdays
- Python 3.11+
- An Alpaca account and a **paper** key pair
- Roughly 20MB of disk for bars and logs

## Install

```bash
sudo mkdir -p /opt/quant-trading-system1
sudo chown "$USER" /opt/quant-trading-system1
git clone <your-repo-url> /opt/quant-trading-system1
cd /opt/quant-trading-system1
pip install -r requirements.txt
pip install alpaca-py
```

## Credentials

```bash
cp .env.example .env
chmod 600 .env          # keys are readable by anyone who can read this file
$EDITOR .env
```

`.env` is gitignored. **Never commit it, never paste keys into a chat, and
rotate any key that has been anywhere it should not have been.**

## Check the account first

Before any data or code, confirm the keys reach Alpaca and the account is
tradable. This uses only the standard library, so it runs before anything is
installed:

```bash
export ALPACA_API_KEY=...  ALPACA_API_SECRET=...
python3 check_account.py
```

It prints equity, cash, buying power, open positions and any blocked-account
flags, then checks the balance against the strategy's sizing. Under $25,000 the
US pattern-day-trader rule applies and positions round to few enough shares that
the risk budget stops being met - results drift from the backtest for reasons
that have nothing to do with the strategy.

## First data pull

`bars/` is not in the repository — it is vendor data and it is per-deployment.
Seed it, then confirm it looks sane:

```bash
set -a && . ./.env && set +a
python3 fetch_bars.py --symbols AAPL,MSFT,NVDA,AMZN,META,GOOGL,AVGO,AMD --start 2020-01-01
python3 -c "import ingest; ingest.status()"
```

Alpaca's free tier serves IEX rather than consolidated prices. For daily bars the
difference is small but real, and it is **not** the data the backtests used — so
expect live signals to differ slightly from a backtest re-run on this data.

## Prove it works before it can spend anything

```bash
# 1. Dry run: no broker, no orders. Shows what it would do.
python3 run_session.py --data ./bars

# 2. Full self-test suite.
python3 test_system.py

# 3. Paper, for real. --live sends orders; with QTS_REAL_MONEY unset they go to
#    the paper endpoint. This is the first time this code has ever placed an order.
QTS_ALLOW_LIVE=yes python3 run_session.py --data ./bars --live
```

Then open Alpaca's dashboard and check, by hand, on the first run:

- Each position has **both** a stop and a take-profit resting against it
- The stop is below entry and the target above it
- Share counts match the dry-run plan
- Risk per position is roughly 1% of equity

Run it on paper for **several weeks** before considering real money. You are
looking for the code to be boring, not for the returns to be good — a few weeks
tells you nothing about a strategy whose backtest contains a 52-trade losing
streak.

## Schedule it

**systemd** (preferred — it has a real timezone and a failure record):

```bash
sudo cp deploy/qts-session.service /etc/systemd/system/
sudo cp deploy/qts-session.timer  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now qts-session.timer
systemctl list-timers qts-session.timer     # confirm the next run
journalctl -u qts-session.service -f        # watch it
```

**cron**: see `deploy/crontab.example`. Set `CRON_TZ` — a server on UTC fires at
the wrong time, and in this system the wrong time means acting on an unfinished
bar.

## Going to real money

Only after paper has run clean for weeks:

```bash
# in .env
QTS_ALLOW_LIVE=yes
QTS_REAL_MONEY=1
```

Both switches plus `--live` are required. Start with a fraction of what you
intend to trade. The backtested 1.0% risk on $100k is roughly $1,000 per position
and up to 15 positions.

## The stop button

```bash
echo "manual halt $(date)" > /opt/quant-trading-system1/HALT
```

Preflight refuses to do anything while that file exists — no redeploy, no code
change, no waiting for a process to notice. Delete it to resume.

## What stops a session on its own

| rail | default | effect |
| --- | --- | --- |
| `HALT` file | — | blocks everything |
| live authorisation | both switches required | `--live` alone does nothing |
| one session per day | — | a rerun cannot double-trade the same signals |
| daily loss | 6% | no new positions for the rest of the day |
| account drawdown | 30% from high water | halts outright |
| market closed | venue clock | no entries outside the session |
| per-position notional | 25% of equity | order rejected |
| per-trade risk | 5% of equity | order rejected |
| total open risk | 10% of equity | order rejected |
| inverted stop/target | — | order rejected |

The last four are re-checks of bounds the sizing code already enforces. That is
the point: they catch the case where the sizing code is itself what broke.

## Operating it

- `session.log` — every decision, appended. The only record of an unattended run.
- `positions_state.json` — what the manager is tracking. **Losing this means
  losing the stop distance, bar count and high-water mark for open positions.**
  Back it up with the ledger.
- `session_ledger.json` — high-water mark and last session date. Deleting it
  re-arms the same-day rail and resets the drawdown breakers.

Check weekly that open positions on Alpaca match `positions_state.json`. The
manager reports unknown holdings rather than adopting them, so a mismatch shows
up as a warning rather than as silent mismanagement — but it still needs a human.

## Known gaps

- **No intraday protection beyond the resting stop.** The trail and the time stop
  only move once a day. A stop that gaps through is filled at the open, as the
  backtest assumed.
- **No alerting.** Failures land in `session.log` and, under systemd, in
  `journalctl`. Nothing pages you.
- **No reconciliation of partial fills mid-session.** The manager catches them on
  the next run, not as they happen.
- **Survivorship bias in every backtest number.** The universe was chosen from
  names liquid today. The dollar figures are not achievable as stated; the
  comparisons between configurations are what the data supports.
