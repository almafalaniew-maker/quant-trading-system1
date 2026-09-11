"""Safety rails for live trading.

The backtest cannot hurt you. A scheduled process holding real API keys can, and
it runs unattended, which means every failure mode has to be caught by code
rather than by somebody noticing. These checks run before any order is placed,
and any one of them failing stops the session.

The ordering is deliberate: cheap local checks first, then account checks, so a
halt file or a wrong-day run costs nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

HALT_FILE = Path("HALT")
LEDGER_FILE = Path("session_ledger.json")

# A live session must clear BOTH of these. A flag alone is too easy to leave in
# a crontab by accident; an env var alone is too easy to leave exported.
LIVE_FLAG_ENV = "QTS_ALLOW_LIVE"


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""

    def __str__(self) -> str:
        return f"[{'PASS' if self.passed else 'BLOCK'}] {self.name}" + (
            f" - {self.detail}" if self.detail else "")


@dataclass
class Limits:
    """Hard bounds the session refuses to cross, whatever the strategy says."""
    max_daily_loss_pct: float = 0.06      # halt for the day past this drawdown
    max_total_drawdown_pct: float = 0.30  # halt outright past this from high water
    max_open_positions: int = 15
    max_position_notional_pct: float = 0.25
    max_portfolio_risk_pct: float = 0.10  # sum of open 1R risk
    min_equity: float = 1_000.0
    require_market_open: bool = True


# ---------------------------------------------------------------------------
# Ledger: what this account has already done, so a rerun cannot double-trade
# ---------------------------------------------------------------------------

@dataclass
class Ledger:
    high_water: float = 0.0
    last_session_date: str = ""
    day_start_equity: float = 0.0
    halted_reason: str = ""

    @classmethod
    def load(cls, path: Path = LEDGER_FILE) -> "Ledger":
        if not path.exists():
            return cls()
        return cls(**json.loads(path.read_text()))

    def save(self, path: Path = LEDGER_FILE) -> None:
        path.write_text(json.dumps(self.__dict__, indent=2))


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

def check_halt_file(path: Path = HALT_FILE) -> Check:
    """A file named HALT stops everything. The simplest kill switch there is:
    `touch HALT` from any shell, no redeploy, no code change."""
    if path.exists():
        reason = path.read_text().strip() or "no reason given"
        return Check("kill switch", False, f"{path} present ({reason})")
    return Check("kill switch", True)


def check_live_authorised(live_requested: bool, env: dict | None = None) -> Check:
    """Live trading needs the flag AND the environment variable.

    Two independent switches because each one alone is easy to leave on by
    accident - a stale crontab entry, or an exported variable in a shell profile.
    """
    env = os.environ if env is None else env
    if not live_requested:
        return Check("live authorisation", True, "paper/dry-run mode")
    if env.get(LIVE_FLAG_ENV) != "yes":
        return Check("live authorisation", False,
                     f"--live passed but {LIVE_FLAG_ENV}=yes is not set")
    return Check("live authorisation", True, "live trading authorised")


def check_credentials(env: dict | None = None) -> Check:
    env = os.environ if env is None else env
    missing = [k for k in ("ALPACA_API_KEY", "ALPACA_API_SECRET") if not env.get(k)]
    if missing:
        return Check("credentials", False, f"missing {', '.join(missing)}")
    return Check("credentials", True)


def check_already_ran_today(ledger: Ledger, today: str) -> Check:
    """One session per trading day.

    The strategy decides once per day at the close. A retry, an overlapping cron
    entry, or a scheduler firing twice would otherwise open a second full set of
    positions on the same signals.
    """
    if ledger.last_session_date == today:
        return Check("one session per day", False, f"already ran for {today}")
    return Check("one session per day", True)


def check_market_open(clock, limits: Limits) -> Check:
    """`clock` is an Alpaca clock object, or None when unavailable."""
    if not limits.require_market_open:
        return Check("market open", True, "check disabled")
    if clock is None:
        return Check("market open", False, "could not read the market clock")
    if not getattr(clock, "is_open", False):
        return Check("market open", False, "market is closed")
    return Check("market open", True)


def check_equity(equity: float, limits: Limits) -> Check:
    if equity < limits.min_equity:
        return Check("minimum equity", False,
                     f"${equity:,.0f} below the ${limits.min_equity:,.0f} floor")
    return Check("minimum equity", True, f"${equity:,.0f}")


def check_drawdown(equity: float, ledger: Ledger, limits: Limits) -> Check:
    """Two circuit breakers: one for today, one for the whole account.

    A strategy with a 26% win rate has long losing streaks by design - the
    backtest contains a 52-trade run of losers. These breakers are not there to
    second-guess a normal streak; they are there for the case where something is
    actually broken and the account is bleeding in a way the backtest never did.
    """
    if ledger.high_water > 0:
        total_dd = 1.0 - equity / ledger.high_water
        if total_dd >= limits.max_total_drawdown_pct:
            return Check("drawdown breaker", False,
                         f"{total_dd:.1%} from high water ${ledger.high_water:,.0f} "
                         f"exceeds the {limits.max_total_drawdown_pct:.0%} limit")
    if ledger.day_start_equity > 0:
        day_dd = 1.0 - equity / ledger.day_start_equity
        if day_dd >= limits.max_daily_loss_pct:
            return Check("drawdown breaker", False,
                         f"down {day_dd:.1%} today, past the "
                         f"{limits.max_daily_loss_pct:.0%} daily limit")
    return Check("drawdown breaker", True)


def check_position_count(open_count: int, limits: Limits) -> Check:
    if open_count > limits.max_open_positions:
        return Check("position count", False,
                     f"{open_count} open, above the {limits.max_open_positions} cap")
    return Check("position count", True, f"{open_count} open")


def validate_order(plan, equity: float, limits: Limits) -> Check:
    """Last line of defence on a single order, just before it is sent.

    Everything here should already be guaranteed by the sizing code. That is
    exactly why it is worth re-checking: this catches the case where the sizing
    code is the thing that is wrong.
    """
    if plan.shares <= 0:
        return Check(f"order {plan.symbol}", False, "non-positive share count")
    if plan.entry_price <= 0:
        return Check(f"order {plan.symbol}", False, "non-positive price")
    if plan.stop_price >= plan.entry_price:
        return Check(f"order {plan.symbol}", False,
                     f"stop {plan.stop_price:.2f} is not below entry "
                     f"{plan.entry_price:.2f} - this would be an instant exit")
    if plan.take_profit_price <= plan.entry_price:
        return Check(f"order {plan.symbol}", False,
                     f"target {plan.take_profit_price:.2f} is not above entry")
    notional = plan.shares * plan.entry_price
    if equity > 0 and notional / equity > limits.max_position_notional_pct:
        return Check(f"order {plan.symbol}", False,
                     f"${notional:,.0f} is {notional/equity:.0%} of equity, above "
                     f"the {limits.max_position_notional_pct:.0%} cap")
    if equity > 0 and plan.risk_dollars / equity > 0.05:
        return Check(f"order {plan.symbol}", False,
                     f"risking ${plan.risk_dollars:,.0f} on one trade is over 5% of equity")
    return Check(f"order {plan.symbol}", True,
                 f"{plan.shares} sh, ${notional:,.0f}, risk ${plan.risk_dollars:,.0f}")


def check_portfolio_risk(open_risk: float, new_risk: float, equity: float,
                         limits: Limits) -> Check:
    """Total open 1R risk, not per-trade risk.

    Fifteen positions at 1% each is 15% of the account riding on one bad
    correlated week, and the backtest showed the system does open clusters.
    """
    if equity <= 0:
        return Check("portfolio risk", False, "no equity")
    total = (open_risk + new_risk) / equity
    if total > limits.max_portfolio_risk_pct:
        return Check("portfolio risk", False,
                     f"{total:.1%} of equity at risk, above the "
                     f"{limits.max_portfolio_risk_pct:.0%} cap")
    return Check("portfolio risk", True, f"{total:.1%} of equity at risk")


# ---------------------------------------------------------------------------

@dataclass
class Preflight:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def blockers(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def report(self) -> str:
        lines = [str(c) for c in self.checks]
        lines.append("PREFLIGHT PASSED" if self.ok else
                     f"PREFLIGHT BLOCKED: {'; '.join(c.detail for c in self.blockers)}")
        return "\n".join(f"  {ln}" for ln in lines)


def preflight(*, live: bool, equity: float, open_count: int, clock,
              ledger: Ledger, today: str, limits: Limits | None = None,
              env: dict | None = None, halt_file: Path = HALT_FILE) -> Preflight:
    """Run every session-level check. Cheap and local first."""
    limits = limits or Limits()
    result = Preflight()
    result.checks.append(check_halt_file(halt_file))
    result.checks.append(check_live_authorised(live, env))
    if live:
        result.checks.append(check_credentials(env))
    result.checks.append(check_already_ran_today(ledger, today))
    result.checks.append(check_equity(equity, limits))
    result.checks.append(check_drawdown(equity, ledger, limits))
    result.checks.append(check_position_count(open_count, limits))
    if live:
        result.checks.append(check_market_open(clock, limits))
    return result
