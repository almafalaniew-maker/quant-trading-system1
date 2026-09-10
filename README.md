# quant-trading-system1

A daily breakout system: signal generation, portfolio backtesting, and live
execution driven by one shared configuration object.

The point of the layout is that `trade_executor.py` imports its filters and
sizing from `strategy.py` — the same module the backtester runs — so live
behaviour cannot quietly drift away from what was tested.

## Layout

| File | Role |
| --- | --- |
| `strategy.py` | `StrategyConfig` plus entry signals, regime gate, position sizing |
| `backtester.py` | Portfolio simulation and the exit state machine |
| `metrics.py` | Win rate, CAGR, drawdown, profit factor, expectancy, yearly returns |
| `data.py` | CSV / yfinance loaders and a synthetic generator for tests |
| `ab_test.py` | Runs the baseline against one-change-at-a-time variants |
| `trade_executor.py` | Live/paper execution, dry-run by default |
| `test_system.py` | Mechanics self-tests |

## Running

```bash
pip install -r requirements.txt
python3 test_system.py                    # mechanics self-tests
python3 ab_test.py --data ./bars          # the real A/B, one CSV per symbol
python3 trade_executor.py --data ./bars   # dry-run scan, no orders sent
```

`ab_test.py --synthetic` runs on generated bars. That path exists to prove the
engine works, not to measure anything: its numbers come from a random seed and
carry no information about edge.

The data directory wants one `<SYMBOL>.csv` per name with `date,open,high,low,
close,volume` columns, adjusted for splits. `SPY.csv` is required for the regime
gate; `QQQ.csv` is required for the strict dual-index regime.

## Configuration

Each testable idea is a field on `StrategyConfig`, so a variant is a config
rather than a forked copy of the code:

```python
baseline = StrategyConfig()
gap_arm  = baseline.variant("gap_required", gap_mode="required", min_gap_pct=0.025)
```

| Field | Options | Note |
| --- | --- | --- |
| `gap_mode` | `ignored` / `required` / `bonus` | `required` is the gap-and-go gate |
| `regime_mode` | `spy_sma` / `dual_index_strict` / `none` | strict = SPY *and* QQQ over 50-SMA and 10-EMA |
| `stop_mode` | `atr` / `fixed_pct` | ATR is the default; see below |
| `exit_mode` | `fixed_target` / `scale_out` | scale-out banks `scale_fraction` at `scale_r`, trails the rest |
| `risk_pct` | fraction of equity | risk budget per trade, not a position size |

## Modelling assumptions

The backtester is deliberately pessimistic wherever daily bars are ambiguous:

* Entries fill at the close of the signal bar; exits are only checked from the
  next bar onward.
* When one bar's range contains both the stop and the target, the stop is
  assumed to have hit first.
* A gap through a level fills at the open, not at the level. A 1R stop can and
  does produce a 2R loss — this is where real drawdowns come from and it must
  not be modelled away.
* Every fill pays slippage (`--cost-bps`, default 5bp) plus per-share commission.

## Status

The engine and its self-tests are complete and passing. **No real-market results
have been produced from this code yet** — this environment's network policy
blocks market data, so the A/B arms have only been exercised on synthetic bars
to verify mechanics. Point `ab_test.py --data` at real daily bars before drawing
any conclusion about which arm is better.
