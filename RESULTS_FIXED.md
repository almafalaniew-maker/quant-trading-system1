# What was broken, what fixing it changed, and how much money it makes

## Four engine defects (found by audit, each measured before fixing)

| # | defect | measured cost |
| --- | --- | --- |
| 1 | Entries **refused** when cash was short instead of being sized down | 42.7% of signals dropped at 0.5% risk; **97.2% at 1.5% risk** |
| 2 | `scale_fraction=0` sold 1 share anyway (`max(1, round(n*0))`) | corrupted every "trail only" arm |
| 3 | The trailing stop could only arm via a scale-out | a trade peaking at 1.9R rode the original stop down |
| 4 | Hold limit counted **calendar** days, and was doing the exiting | 27% of 8R trades, averaging **+2.99R, 97% profitable** |

Defect 1 is why "raising risk backfires" appeared in the earlier run. It was
never a risk finding — the engine was deleting signals rather than buying
smaller. That conclusion is withdrawn.

All four are fixed, with six new tests covering them (32 assertions passing).

## The hypothesis that was wrong

The time stop was closing profitable trends, so a trailing stop should free them.
**It doesn't.** Trailing loses to a plain 8R target in all three windows:

| arm | out-of-sample | tuning window | 20 years |
| --- | ---: | ---: | ---: |
| baseline 4R | $305,749 | $204,797 | $631,091 |
| **8R target** | **$407,889** | **$239,676** | **$1,032,591** |
| 8R + trail from 2R | $263,697 | $219,146 | $645,674 |
| trail from entry | $228,499 | $172,967 | $390,980 |
| trail from 1R | $220,317 | $171,388 | $376,773 |

Trailing raises win rate (33% → 40%) and lowers money, the same trade the
scale-out made. A 3×ATR trail gets hit by a routine pullback; a distant target
lets the trend breathe.

The right fix was the cheaper one: **give trades more bars, don't change the
exit rule.**

| arm | out-of-sample | tuning | 20 years | 20y cagr | 20y maxDD |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8R target (83 bars) | $407,889 | $239,676 | $1,032,591 | 12.0% | 29.1% |
| 8R + 120 bars | $495,049 | $203,252 | $1,153,885 | 12.6% | 31.1% |
| 8R + 180 bars | $477,313 | $200,858 | $1,060,969 | 12.1% | 35.0% |
| **8R + 250 bars** | **$511,282** | $227,513 | **$1,358,958** | **13.4%** | 35.6% |

Note 120 > 180 < 250 — not monotonic. The exact bar count is partly noise, so
treat "give it roughly a year" as the finding, not "250".

Position-cap sweep (8%/10%/12%/15%/20%) moved almost nothing: $892k–$1,090k over
20 years, no clear direction. Dropped.

## Making the most money

With the cash defect fixed, position size can finally be measured. This is the
only lever here that is not a parameter fitted to this data.

**Full 20 years, from $100,000:**

| risk/trade | trades | ending | cagr | maxDD | worst loss | sharpe | MAR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.50% | 719 | $1,358,958 | 13.4% | 35.6% | $35,618 | 0.95 | **0.38** |
| 0.75% | 616 | $2,191,720 | 16.1% | 43.3% | $43,308 | 0.95 | 0.37 |
| 1.00% | 543 | $2,609,285 | 17.1% | 48.5% | $48,520 | 0.93 | 0.35 |
| **1.00%, 15 slots** | 574 | **$2,859,743** | **17.6%** | 49.4% | $49,396 | **0.96** | 0.36 |
| 1.50% | 479 | $2,801,358 | 17.5% | 48.3% | $48,279 | 0.91 | 0.36 |
| 2.00% | 427 | $2,447,423 | 16.7% | 50.1% | $50,150 | 0.84 | 0.33 |
| SPY buy & hold | — | $606,935 | 9.1% | 56.5% | $56,474 | 0.55 | 0.16 |

**Most money: 8R target, ~250-bar hold, 1.0–1.5% risk, 15 slots — about $2.86M
on $100k over 20 years, against SPY's $607k.**

Two things that table is telling you:

**Returns fall off above 1.5%.** 2.00% makes *less* money than 1.50% with a worse
drawdown. That is the overbetting cliff, and it is where accounts die.

**Sharpe is flat (0.91–0.96) and MAR *declines* with size.** Extra risk buys extra
money linearly, not extra skill. Nothing above 0.5% improves the quality of the
returns — it only scales them, right up until it stops working.

## What that actually felt like

The $2.8M arm, lived through:

- **48.3% drawdown**: $118,933 on 2007-10-10 → **$61,513** on 2009-02-23.
- **39 months** to make it back — not recovered until 2010-12-29.
- 4 losing years of 21. Worst year **−36.0%**. Best year +100.2%.

Losing 48% and waiting three and a half years is where nearly everyone abandons
the system. The 0.5% arm has the best MAR (0.38) and a 35.6% worst case, and
still ends at $1.36M against SPY's $607k.

## The caveat that governs every number above

All 60 names were selected because they are liquid and listed **today**. No
delisted or bankrupt company is in the set. Buying MU, LRCX, AMAT and AVGO in
2006 is hindsight. **The dollar figures are inflated and not achievable**; the
comparisons *between* arms are what this data supports, because every arm is
handicapped identically.

The defensible claim is the relative one: **against SPY over 20 years, roughly
double the CAGR at a slightly lower maximum drawdown, Sharpe 0.96 vs 0.55.**
