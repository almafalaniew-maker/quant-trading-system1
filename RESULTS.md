# A/B results — real market data

**Data:** 40 US large/mid-cap equities plus SPY and QQQ, daily split-adjusted bars
from the trading connector, 2021-01-04 → 2026-09-09 (1,424 sessions, 59,738 bars).
One untradeable bar dropped (COIN's IPO print, where the $250 "open" is an
offering reference and the $310 low is where trading actually started).

**Engine assumptions:** entry at the signal bar's close; stop assumed to win any
bar that spans both stop and target; gaps through a level fill at the open, not
the level; 5bp slippage plus $0.005/share commission on every fill; 0.5% equity
risk per trade, max 10 concurrent positions.

## Headline table

| variant | trades | win% | ret% | cagr% | maxDD% | PF | exp_R | avgW_R | avgL_R | sharpe |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline (fixed 4R) | 421 | 31.8 | 112.5 | 14.2 | 24.1 | 1.56 | 0.41 | 3.53 | -1.05 | 0.96 |
| **gap ≥ 2.5% required** | 315 | **38.1** | **175.8** | **19.6** | **18.1** | **2.14** | **0.70** | 3.52 | -1.03 | **1.42** |
| gap ≥ 1.5% required | 370 | 33.2 | 123.9 | 15.3 | 22.0 | 1.72 | 0.49 | 3.53 | -1.03 | 1.03 |
| gap ranked first (no gate) | 389 | 34.7 | 147.4 | 17.3 | 20.4 | 1.79 | 0.52 | 3.46 | -1.05 | 1.15 |
| strict regime (SPY+QQQ) | 369 | 33.3 | 124.4 | 15.3 | 25.6 | 1.67 | 0.50 | 3.61 | -1.06 | 1.07 |
| scale-out at 2R | 466 | 42.1 | 103.1 | 13.3 | 24.0 | 1.58 | 0.33 | 2.23 | -1.04 | 1.04 |
| fixed 2% stop | 884 | 24.8 | 56.2 | 8.2 | 24.3 | 1.14 | 0.14 | 4.23 | -1.20 | 0.61 |
| risk 0.25% | 419 | 32.7 | 53.2 | 7.8 | 11.7 | 1.61 | 0.44 | 3.50 | -1.05 | 1.02 |
| gap + scale-out | 332 | 44.9 | 86.9 | 11.6 | 15.4 | 1.70 | 0.41 | 2.20 | -1.05 | 1.06 |
| gap + strict regime + scale-out | 301 | 46.2 | 82.7 | 11.2 | 15.1 | 1.78 | 0.43 | 2.17 | -1.06 | 1.08 |

## The benchmark that matters

| | total | cagr | maxDD | sharpe |
| --- | ---: | ---: | ---: | ---: |
| SPY buy & hold | 106.7% | 13.6% | 25.4% | 0.85 |
| QQQ buy & hold | 131.6% | 15.9% | 35.6% | 0.77 |
| **equal-weight the same 40 names, buy & hold** | **264.8%** | **25.6%** | 36.3% | 1.03 |
| best strategy arm (gap ≥ 2.5%) | 175.8% | 19.6% | **18.1%** | **1.42** |

Holding the same basket beat every strategy arm on raw return by a wide margin.
The strategy's case is risk-adjusted, not absolute: half the drawdown and a
materially better Sharpe. Anyone quoting the +175.8% without this row is quoting
a number that flatters the system.

Note also what this row says about the universe: these 40 names returned 265%
equal-weight against SPY's 107%. The basket was picked from today's liquid
large caps, so it is loaded with survivors. Every arm above is inflated by that
selection; the comparisons *between* arms are the trustworthy part.

## Gap threshold sweep

| gate | trades | win% | exp_R | PF | ret% | maxDD% | sharpe |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| none | 421 | 31.8 | 0.407 | 1.56 | 112.5 | 24.1 | 0.96 |
| 0.5% | 394 | 34.8 | 0.544 | 1.89 | 162.8 | 21.0 | 1.20 |
| 1.0% | 377 | 34.7 | 0.556 | 1.89 | 156.2 | 21.6 | 1.19 |
| 1.5% | 370 | 33.2 | 0.486 | 1.72 | 123.9 | 22.0 | 1.03 |
| 2.0% | 348 | 34.2 | 0.544 | 1.79 | 133.5 | 21.6 | 1.16 |
| 2.5% | 315 | 38.1 | 0.705 | 2.14 | 175.8 | 18.1 | 1.42 |
| 3.0% | 278 | 38.8 | 0.746 | 2.14 | 157.8 | 15.0 | 1.42 |
| 4.0% | 232 | 39.7 | 0.716 | 2.19 | 113.0 | 16.8 | 1.26 |
| 5.0% | 200 | 39.0 | 0.686 | 2.06 | 86.9 | 14.5 | 1.17 |

Every gate beats no gate on expectancy, and win rate rises with the threshold
(correlation +0.83). Expectancy plateaus across 2.5–4%, so 2.5% is a plateau
rather than a spike — the shape a real effect makes, not the shape overfitting
makes. Return falls above 3% because the trade count drops faster than the edge
per trade improves.

## Does it survive splitting the sample?

| half | arm | trades | win% | exp_R | ret% | PF |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| first (to 2023-11-02) | no gate | 182 | 26.4 | +0.102 | 7.0 | 1.09 |
| first | gap ≥ 2.5% | 127 | 27.6 | +0.214 | 12.4 | 1.26 |
| second (after 2023-11-02) | no gate | 227 | 33.5 | +0.491 | 64.2 | 1.64 |
| second | gap ≥ 2.5% | 182 | 43.4 | +0.901 | 112.8 | 2.37 |

Same direction in both halves, far stronger in the second.

## Significance

- Expectancy: baseline +0.407R (n=421) vs gap +0.705R (n=315). Difference
  +0.298R, standard error 0.173, **t = 1.73** — short of the 5% threshold.
- Win rate: 31.8% vs 38.1%, difference +6.3pts, **z = 1.77** — also short.

So: consistent in direction across nine thresholds and both halves, but the
sample is not large enough to rule out chance at the conventional bar. Treat the
gap filter as promising and worth trading small, not as established.
