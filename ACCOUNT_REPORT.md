# Full account report — best configuration

**Config:** 8R target, 250-bar hold, 1.0% risk per trade, 15 slots, ATR stop,
SPY 50-day regime gate. Chosen because it won out-of-sample (2006–2020) as well
as over the full period — not because it topped one sweep.

## Headline

| | |
| --- | --- |
| Period | 2006-01-03 → 2026-09-09 (20.7 years) |
| Starting capital | $100,000 |
| **Ending capital** | **$2,859,743** |
| **Profit** | **$2,759,743** |
| Total return | 2,759.7% |
| Compound annual | **17.60%** |
| Multiple | 28.6× |
| SPY over the same period | $606,935 (9.1% CAGR) |

## Risk

| | |
| --- | --- |
| Worst drawdown | **49.4%** |
| From / to | $110,132 (2007-10-10) → $55,731 (2009-03-30) |
| Time underwater | **39 months** — recovered 2011-01-05 |
| Sharpe | 0.96 (SPY 0.55) |
| MAR | 0.36 |
| Time in market | 97% of days |

## Trades

574 trades. **150 winners (26.1%), 424 losers (73.9%).**

| | |
| --- | --- |
| Gross profit | $4,830,949 |
| Gross loss | −$2,072,681 |
| Profit factor | 2.33 |
| Average win | $32,206 (+6.68R) |
| Average loss | −$4,888 (−1.08R) |
| Win/loss size ratio | **6.59×** |
| Expectancy per trade | $4,805 (+0.948R) |
| Largest win | $218,483 (+10.80R, SNOW) |
| Largest loss | −$31,568 (−2.69R) |
| Longest win streak | 10 |
| **Longest losing streak** | **52** |

This only works because winners are 6.6× the size of losers. Three out of four
trades lose money. A 52-trade losing streak is in the record.

**How trades ended**

| reason | count | share | total | avg |
| --- | ---: | ---: | ---: | ---: |
| stop | 423 | 73.7% | −$2,070,526 | −1.08R |
| target | 105 | 18.3% | $4,283,568 | +8.10R |
| time_stop | 36 | 6.3% | $292,073 | +3.88R |
| end_of_test | 10 | 1.7% | $253,153 | +1.12R |

## Year by year

| year | trades | return | profit | balance | SPY |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2006 | 20 | 1.7% | $1,684 | $101,684 | 12.7% |
| 2007 | 31 | −0.4% | −$423 | $101,261 | 3.2% |
| 2008 | 43 | **−36.2%** | −$36,623 | $64,637 | −39.1% |
| 2009 | 24 | 30.8% | $19,882 | $84,519 | 25.3% |
| 2010 | 19 | 28.0% | $23,673 | $108,192 | 12.8% |
| 2011 | 26 | −6.7% | −$7,198 | $100,994 | −0.2% |
| 2012 | 10 | 20.7% | $20,923 | $121,917 | 13.5% |
| 2013 | 25 | 53.0% | $64,580 | $186,497 | 29.7% |
| 2014 | 19 | 15.1% | $28,243 | $214,741 | 12.4% |
| 2015 | 30 | −2.5% | −$5,376 | $209,365 | −1.8% |
| 2016 | 20 | 10.8% | $22,619 | $231,983 | 9.6% |
| 2017 | 26 | 28.0% | $65,036 | $297,019 | 19.4% |
| 2018 | 28 | 7.7% | $23,009 | $320,029 | −6.3% |
| 2019 | 18 | 34.5% | $110,450 | $430,479 | 28.8% |
| 2020 | 44 | **79.9%** | $343,779 | $774,257 | 15.6% |
| 2021 | 34 | 26.4% | $204,554 | $978,811 | 28.0% |
| 2022 | 23 | −7.4% | −$72,263 | $906,548 | −19.7% |
| 2023 | 34 | 53.7% | $486,815 | $1,393,363 | 24.3% |
| 2024 | 30 | 42.9% | $597,116 | $1,990,479 | 23.8% |
| 2025 | 27 | 23.1% | $459,136 | $2,449,615 | 16.8% |
| 2026 | 43 | 16.7% | $410,127 | $2,859,743 | 11.0% |

**16 winning years of 21. Beat SPY in 16 of 21.** Worst −36.2% (2008, when SPY
lost 39.1% — the regime gate barely helped). Best +79.9% (2020).

## Concentration — the structural risk

- **Only 35 of 60 names were profitable.**
- Top 5 names: **$1,377,695 — 50% of all profit.**
- Top 10 names: $2,104,961 — **76%.**
- Top earners: ANET $439,526 · AVGO $390,164 · SNOW $188,240 · DDOG $186,883 · AMAT $172,882
- Worst: ABNB −$42,047 · NFLX −$38,898 (0 for 9) · META −$38,635 · COIN −$31,434

Worse, the biggest wins cluster on a handful of entry dates. **2025-05-01
(DDOG, AVGO, ANET) and 2026-04-08 (INTC, ON, MU) produced $1,009,663 between
them — 37% of all profit from two days' entries.** Entry clustering overall is
mild (median 1 position/day, 20% of trades on 5+ position days, and 13 of 18
clusters had mixed outcomes), but the *profit* is not mild in its concentration.
Remove those two days and the record looks materially different.

## By holding period

| window | trades | ending | profit | cagr | maxDD | SPY ending |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 year | 54 | $120,326 | $20,326 | 20.4% | 15.2% | $116,895 |
| 3 years | 122 | $146,374 | $46,374 | **13.6%** | 24.6% | **$170,008** |
| 5 years | 184 | $290,323 | $190,323 | 23.8% | 20.3% | $171,157 |
| 10 years | 299 | $940,161 | $840,161 | 25.1% | 23.5% | $352,408 |
| 20 years | 574 | $2,859,743 | $2,759,743 | 17.6% | 49.4% | $606,935 |

**Over the last three years the system lost to SPY** — 13.6% CAGR against 19.4%,
at a worse drawdown. Worth knowing before trusting the 20-year figure.

## What governs all of it

All 60 names were selected because they are liquid and listed **today**. No
delisted or bankrupt company is in the set, and half the profit came from five
names nobody could have known to pick in 2006. **The dollar figures are inflated
and not achievable as stated.** What the data supports is the relative claim —
every arm and benchmark is handicapped identically — and even that rests on a
26% win rate carried by a handful of outliers.
