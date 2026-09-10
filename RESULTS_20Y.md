# Twenty-year results, and why the strategy trailed buy-and-hold

**Data:** 60 US equities plus SPY/QQQ, daily split-adjusted, 2006-01-03 → 2026-09-09
(5,196 sessions, 280,584 bars) from the trading connector. Three IPO-day bars
dropped (ABNB, COIN, CRWD) where the printed open is an offering reference.

## Why it lost to buy-and-hold

Three candidates were measured, not guessed:

1. **Under-invested.** Mean invested notional 68% of equity (median 77%), 8.2 of
   10 slots filled. Buy-and-hold runs at 100%.
2. **The 4R target was the leak.** 104 trades exited at the target; the median of
   those went on to **7.3R** within 120 days, the top decile to 15.1R. Capping at
   4R left **489R** on the table.
3. **Not the regime gate** — only 7.9% of days were fully flat.

Raising the cap improved return *and* drawdown together on the tuning window:

| target | trades | ret% | cagr% | maxDD% | sharpe |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4R | 421 | 112.5 | 14.2 | 24.1 | 0.96 |
| 6R | 341 | 149.0 | 17.4 | 22.8 | 1.13 |
| 8R | 328 | 152.5 | 17.7 | 23.0 | 1.10 |
| 12R | 309 | 171.7 | 19.3 | 19.3 | 1.16 |

**Raising risk per trade backfired** — 1.0% risk gave 74.6% return and a 35%
drawdown against baseline's 112.5%/24.1%, and 20 slots changed nothing at all.
The book is cash-constrained, not slot-constrained: bigger positions simply
crowd out later trades.

## The out-of-sample test that matters

Both the 12R cap and the 2.5% gap gate were chosen by looking at 2021-2026.
On 2006-2020 they behave very differently:

| variant | trades | win% | ret% | cagr% | maxDD% |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline 4R | 859 | 32.1 | 212.7 | 7.9 | 32.2 |
| target 8R | 696 | 32.8 | **320.4** | **10.1** | 31.8 |
| target 12R | 695 | 32.2 | 279.7 | 9.3 | 30.2 |
| gap ≥ 2.5% only | 568 | 34.7 | 150.7 | 6.3 | **20.3** |
| gap + 12R ("the fix") | 509 | 33.4 | 150.0 | 6.3 | 20.2 |

**The raised target generalises. The gap filter does not.** Out-of-sample the gap
gate *cut return by a third* (212.7% → 150.7%) while cutting drawdown by a third
(32.2% → 20.3%). It is a risk reducer, not a return enhancer — the opposite of
what the 2021-2026 window suggested. Shipping both as one change would have
hidden that.

## By holding period, starting with $100,000

| window | strategy | trades | win% | ending | profit | cagr | maxDD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 year | baseline 4R | 79 | 36.7 | $118,117 | $18,117 | 18.2% | 5.7% |
| | gap + 12R | 44 | 40.9 | $119,920 | $19,920 | 20.0% | 12.6% |
| | SPY | — | — | $116,895 | $16,895 | 17.0% | 9.1% |
| | equal-weight hold | — | — | $147,518 | $47,518 | 47.7% | 12.0% |
| 3 years | baseline 4R | 229 | 34.9 | $165,195 | $65,195 | 18.2% | 12.9% |
| | gap + 12R | 127 | 44.9 | $233,226 | $133,226 | 32.7% | 12.6% |
| | SPY | — | — | $170,008 | $70,008 | 19.4% | 19.0% |
| | equal-weight hold | — | — | $232,143 | $132,143 | 32.5% | 26.2% |
| 10 years | baseline 4R | 681 | 32.6 | $342,138 | $242,138 | 13.1% | 20.6% |
| | gap + 12R | 416 | 34.9 | $371,626 | $271,626 | 14.0% | 20.3% |
| | SPY | — | — | $352,408 | $252,408 | 13.4% | 34.1% |
| | equal-weight hold | — | — | $1,194,627 | $1,094,627 | 28.2% | 47.7% |
| 20 years | baseline 4R | 1,265 | 32.2 | $672,342 | $572,342 | 9.7% | 32.2% |
| | gap + 12R | 751 | 34.1 | $605,924 | $505,924 | 9.1% | 20.5% |
| | SPY | — | — | $606,935 | $506,935 | 9.1% | **56.5%** |
| | equal-weight hold | — | — | $3,864,198 | $3,764,198 | 19.3% | 49.1% |

**Against SPY over 20 years the system matches the return (9.1% vs 9.1%) on a
third of the drawdown (20.5% vs 56.5%), Sharpe 0.77 vs 0.55.** That is the fair
comparison and it is a real result.

**The equal-weight column is not a fair benchmark.** All 60 names were picked
because they are liquid and listed *today*. Buying MU, LRCX, AMAT, NVDA and AVGO
in 2006 and holding for twenty years is hindsight, not a strategy — no delisted
or bankrupt name is in this set. The strategy numbers carry the same bias but
far less of it, because the strategy still has to time entries and can lose money
on any name in the list.

## What it actually traded (20 years, gap + 12R)

751 trades across 60 names.

| symbol | trades | P&L | win rate | best |
| --- | ---: | ---: | ---: | ---: |
| MU | 39 | $71,637 | 36% | 12.0R |
| LRCX | 19 | $46,001 | 47% | 12.0R |
| AMAT | 18 | $39,672 | 44% | 12.0R |
| GOOGL | 21 | $26,327 | 48% | 7.4R |
| WMT | 10 | $23,161 | 40% | 7.7R |
| AVGO | 18 | $22,403 | 50% | 6.9R |
| ... | | | | |
| IBM | 7 | -$6,633 | **0%** | -0.1R |
| AMGN | 8 | -$8,093 | **0%** | -1.0R |

**The top 10 names produced $302,159 of $505,740 — 60% of all profit.** Trade
count is steady at 17-49 per year across all twenty years, so the system is not
dependent on one regime for opportunities.

### A structural problem the 12R cap created

Exit reasons: 481 stops, 253 **time stops**, 10 end-of-test, and only **7 targets**.
A 12R cap is effectively no target at all, which promotes `max_hold_days=120` —
an arbitrary calendar limit — into the system's main profit-taking rule. Winners
are being cut at 120 days regardless of whether they are still trending. Replacing
the time stop with a trailing stop is the obvious next test and has not been run.
