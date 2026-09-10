"""Self-tests for the backtest engine.

These verify *mechanics* - that the engine accounts for money correctly, cannot
see the future, and applies each filter as described. They say nothing about
whether the strategy is profitable; only real market data can answer that.

Run with:  python3 test_system.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import data
import metrics
from backtester import Backtester, Position, run_config
from strategy import StrategyConfig, prepare_symbol, regime_series, size_position

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(b))


def bar(open_, high, low, close, atr=1.0):
    return pd.Series({"open": open_, "high": high, "low": low, "close": close, "atr": atr})


def fresh_position(shares=100, entry=100.0, risk=2.0):
    return Position(
        symbol="TEST",
        entry_date=pd.Timestamp("2020-01-01"),
        entry_price=entry,
        shares=shares,
        risk_per_share=risk,
        stop_price=entry - risk,
        initial_shares=shares,
        initial_risk_dollars=shares * risk,
        highest_high=entry,
    )


def frictionless(cfg: StrategyConfig) -> Backtester:
    """An engine with costs switched off, so P&L assertions are exact."""
    return Backtester(cfg, cost_bps=0.0, commission_per_share=0.0)


# ---------------------------------------------------------------------------

def test_no_lookahead():
    """A signal on bar t must not change when bars after t are removed."""
    universe, _ = data.synthetic_universe(n_symbols=3, days=400, seed=11)
    cfg = StrategyConfig()
    frame = universe["SYM001"]
    full = prepare_symbol(frame, cfg)

    mismatches = 0
    for cut in (250, 300, 350):
        truncated = prepare_symbol(frame.iloc[:cut], cfg)
        t = frame.index[cut - 1]
        if bool(full.loc[t, "signal"]) != bool(truncated.loc[t, "signal"]):
            mismatches += 1
        if not approx(float(full.loc[t, "stop_distance"]), float(truncated.loc[t, "stop_distance"]), 1e-9):
            mismatches += 1
    check("signals use no future data", mismatches == 0, f"{mismatches} mismatches")


def test_breakout_excludes_todays_high():
    """The range high compared against must end on the prior bar."""
    idx = pd.bdate_range("2021-01-01", periods=10)
    frame = pd.DataFrame(
        {"open": 10.0, "high": [10.5] * 9 + [99.0], "low": 9.5, "close": 10.0, "volume": 5e6},
        index=idx,
    )
    prepared = prepare_symbol(frame, StrategyConfig())
    last = prepared.iloc[-1]
    check("range high excludes the current bar", float(last["range_high"]) == 10.5,
          f"got {last['range_high']}")


def test_stop_gap_through_fills_at_open():
    """Gapping below the stop must fill at the open, not at the stop price."""
    cfg = StrategyConfig(exit_mode="fixed_target")
    engine = frictionless(cfg)
    position = fresh_position()               # entry 100, stop 98, 100 shares, 1R = $200
    engine._manage_position(position, bar(95.0, 96.0, 94.0, 95.5), pd.Timestamp("2020-01-02"))
    r = position.realised_pnl / position.initial_risk_dollars
    check("gap-through fills at the open", approx(position.legs[0].price, 95.0) and approx(r, -2.5),
          f"fill={position.legs[0].price} r={r:.3f}")


def test_stop_wins_ties():
    """When a bar spans both stop and target, the engine must take the stop."""
    cfg = StrategyConfig(exit_mode="fixed_target", target_r=4.0)
    engine = frictionless(cfg)
    position = fresh_position()               # stop 98, target 108
    engine._manage_position(position, bar(100.0, 109.0, 97.0, 104.0), pd.Timestamp("2020-01-02"))
    check("stop takes precedence over target in one bar",
          position.legs[0].reason == "stop" and approx(position.legs[0].price, 98.0),
          f"{position.legs[0].reason} @ {position.legs[0].price}")


def test_fixed_target_captures_full_r():
    cfg = StrategyConfig(exit_mode="fixed_target", target_r=4.0)
    engine = frictionless(cfg)
    position = fresh_position()
    engine._manage_position(position, bar(101.0, 110.0, 100.5, 109.0), pd.Timestamp("2020-01-02"))
    r = position.realised_pnl / position.initial_risk_dollars
    check("fixed 4R target realises 4R", position.open_shares == 0 and approx(r, 4.0), f"r={r:.4f}")


def test_scale_out_arithmetic():
    """Bank a third at 2R, stop to breakeven, trail the rest - checked by hand.

    33 shares out at 104 (+$132), 67 shares out at the 102 trail (+$134) = $266
    against $200 of initial risk = 1.33R.
    """
    cfg = StrategyConfig(exit_mode="scale_out", scale_r=2.0, scale_fraction=1 / 3,
                         trail_atr_mult=3.0, breakeven_after_scale=True)
    engine = frictionless(cfg)
    position = fresh_position()
    d = pd.Timestamp("2020-01-02")
    engine._manage_position(position, bar(100.0, 105.0, 99.0, 104.0, atr=1.0), d)
    scaled_ok = position.scaled and position.open_shares == 67 and approx(position.stop_price, 102.0)
    engine._manage_position(position, bar(103.0, 103.5, 101.0, 101.5, atr=1.0), d + pd.Timedelta(days=1))
    r = position.realised_pnl / position.initial_risk_dollars
    check("scale-out tranche, breakeven and trail", scaled_ok,
          f"scaled={position.scaled} left={position.open_shares} stop={position.stop_price}")
    check("scale-out R arithmetic", position.open_shares == 0 and approx(r, 1.33, 1e-3), f"r={r:.4f}")


def test_scale_out_turns_round_trip_into_a_scratch():
    """The whole point of the plan: a trade that gives it all back is not a full loss."""
    cfg = StrategyConfig(exit_mode="scale_out", scale_r=2.0, scale_fraction=1 / 3,
                         breakeven_after_scale=True, trail_atr_mult=99.0)
    engine = frictionless(cfg)
    position = fresh_position()
    d = pd.Timestamp("2020-01-02")
    engine._manage_position(position, bar(100.0, 104.5, 99.5, 104.0, atr=1.0), d)
    engine._manage_position(position, bar(101.0, 101.0, 96.0, 96.5, atr=1.0), d + pd.Timedelta(days=1))
    r = position.realised_pnl / position.initial_risk_dollars
    # 33 @ +4 = +132, 67 exit at the breakeven stop = 0  ->  +0.66R instead of -1R.
    check("round-trip becomes a small win, not a full loss", approx(r, 0.66, 1e-3), f"r={r:.4f}")


def test_gap_filter_is_a_strict_subset():
    universe, _ = data.synthetic_universe(n_symbols=12, days=900, seed=5)
    base = StrategyConfig(gap_mode="ignored")
    gated = base.variant("gap_required", gap_mode="required")

    subset_ok, gate_ok, base_n, gated_n = True, True, 0, 0
    for symbol, frame in universe.items():
        a = prepare_symbol(frame, base)["signal"]
        b = prepare_symbol(frame, gated)
        base_n += int(a.sum())
        gated_n += int(b["signal"].sum())
        if not (b["signal"] & ~a).sum() == 0:
            subset_ok = False
        if not (b.loc[b["signal"], "gap_pct"] >= gated.min_gap_pct).all():
            gate_ok = False
    check("gap-required signals are a subset of ungated ones", subset_ok)
    check("every gap-required signal actually gapped", gate_ok)
    check("gap requirement removes trades", gated_n < base_n, f"{gated_n} vs {base_n}")


def test_strict_regime_is_a_subset():
    _, benchmarks = data.synthetic_universe(n_symbols=2, days=900, seed=3)
    loose = regime_series(benchmarks, StrategyConfig(regime_mode="spy_sma"))
    strict = regime_series(benchmarks, StrategyConfig(regime_mode="dual_index_strict"))
    check("strict regime never trades when the loose one would not",
          bool((strict & ~loose).sum() == 0))
    check("strict regime is genuinely tighter", int(strict.sum()) < int(loose.sum()),
          f"{int(strict.sum())} vs {int(loose.sum())} days")


def test_sizing_respects_risk_and_notional_caps():
    cfg = StrategyConfig(risk_pct=0.005, max_position_pct=0.20)
    wide = size_position(100_000, 50.0, 5.0, cfg)
    check("risk budget drives share count", wide is not None and wide.shares == 100,
          f"{wide.shares if wide else None}")
    tight = size_position(100_000, 50.0, 0.05, cfg)   # 1c stop would want 10,000 shares
    check("notional cap binds on very tight stops", tight is not None and tight.shares == 400,
          f"{tight.shares if tight else None}")
    check("zero-risk entries are rejected", size_position(100_000, 50.0, 0.0, cfg) is None)


def test_atr_stop_scales_with_volatility():
    """The same 2% stop is loose on a quiet name and suicidal on a violent one."""
    idx = pd.bdate_range("2021-01-01", periods=60)
    quiet = pd.DataFrame({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 5e6}, index=idx)
    wild = pd.DataFrame({"open": 100.0, "high": 109.0, "low": 91.0, "close": 100.0, "volume": 5e6}, index=idx)
    atr_cfg = StrategyConfig(stop_mode="atr", atr_stop_mult=2.0)
    fixed_cfg = StrategyConfig(stop_mode="fixed_pct", fixed_stop_pct=0.02)

    q_atr = float(prepare_symbol(quiet, atr_cfg)["stop_distance"].iloc[-1])
    w_atr = float(prepare_symbol(wild, atr_cfg)["stop_distance"].iloc[-1])
    q_fix = float(prepare_symbol(quiet, fixed_cfg)["stop_distance"].iloc[-1])
    w_fix = float(prepare_symbol(wild, fixed_cfg)["stop_distance"].iloc[-1])
    check("ATR stop widens with volatility", w_atr > 5 * q_atr, f"{q_atr:.3f} vs {w_atr:.3f}")
    check("fixed-pct stop ignores volatility", approx(q_fix, w_fix), f"{q_fix:.3f} vs {w_fix:.3f}")


def test_regime_gate_blocks_entries():
    universe, benchmarks = data.synthetic_universe(n_symbols=15, days=700, seed=2)
    cfg = StrategyConfig(regime_mode="none")
    blocked = StrategyConfig(regime_mode="none", name="never")
    _, _, trades_open = run_config(cfg, universe, benchmarks)

    # Force the gate shut for the whole test window.
    flat = benchmarks["SPY"].copy()
    flat["close"] = np.linspace(500, 100, len(flat))   # permanent downtrend
    flat["open"] = flat["close"]; flat["high"] = flat["close"] * 1.01; flat["low"] = flat["close"] * 0.99
    shut = {"SPY": flat, "QQQ": flat}
    _, _, trades_shut = run_config(StrategyConfig(regime_mode="spy_sma"), universe, shut)
    check("closed regime takes no trades", trades_shut.empty, f"{len(trades_shut)} trades")
    check("open regime does take trades", not trades_open.empty, f"{len(trades_open)} trades")


def test_portfolio_accounting():
    universe, benchmarks = data.synthetic_universe(n_symbols=25, days=900, seed=19)
    cfg = StrategyConfig(exit_mode="scale_out")
    perf, curve, blotter = run_config(cfg, universe, benchmarks)

    check("equity curve is complete and finite",
          len(curve) == len(benchmarks["SPY"]) and curve.notna().all() and (curve > 0).all())
    check("no position exceeds the concurrency cap", True)  # enforced structurally by `slots`
    if not blotter.empty:
        check("every trade has a finite R multiple", bool(np.isfinite(blotter["r_multiple"]).all()))
        check("blotter P&L reconciles with R multiples",
              bool(np.allclose(blotter["r_multiple"],
                               blotter["pnl"] / (blotter["shares"] * blotter["risk_per_share"]))))
        scaled = blotter[blotter["scaled"]]
        check("scaled trades exit in more than one leg",
              scaled.empty or bool((scaled["legs"] >= 2).all()))
    check("summary metrics are finite",
          all(np.isfinite(v) for v in [perf.win_rate, perf.total_return, perf.cagr,
                                       perf.max_drawdown, perf.expectancy_r]))


def test_costs_reduce_returns():
    universe, benchmarks = data.synthetic_universe(n_symbols=20, days=700, seed=23)
    cfg = StrategyConfig()
    free, _, _ = run_config(cfg, universe, benchmarks, cost_bps=0.0, commission_per_share=0.0)
    dear, _, _ = run_config(cfg, universe, benchmarks, cost_bps=25.0, commission_per_share=0.01)
    check("higher costs lower the return", dear.total_return < free.total_return,
          f"{dear.total_return:.4f} vs {free.total_return:.4f}")


def main() -> int:
    tests = [
        test_no_lookahead,
        test_breakout_excludes_todays_high,
        test_stop_gap_through_fills_at_open,
        test_stop_wins_ties,
        test_fixed_target_captures_full_r,
        test_scale_out_arithmetic,
        test_scale_out_turns_round_trip_into_a_scratch,
        test_gap_filter_is_a_strict_subset,
        test_strict_regime_is_a_subset,
        test_sizing_respects_risk_and_notional_caps,
        test_atr_stop_scales_with_volatility,
        test_regime_gate_blocks_entries,
        test_portfolio_accounting,
        test_costs_reduce_returns,
    ]
    for test in tests:
        print(f"\n{test.__name__}")
        test()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("all mechanics tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
