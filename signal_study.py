"""Is the gap edge about the gap, or is the gap standing in for something else?

Gapping stocks are not a random sample of breakouts. They are more volatile,
they have usually just run, and they trade on a volume spike. Any of those could
be carrying the edge that the gap gate appears to capture.

The portfolio backtest cannot settle this: it caps concurrent positions, so most
signals never become trades and the ones that do are picked by the ranking rule.
This module evaluates every signal in isolation instead - unlimited capacity,
one trade per signal - which removes the capacity confound and multiplies the
sample. Then it compares gappers against non-gappers that look like them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import data as data_mod
from backtester import Backtester, Position
from strategy import StrategyConfig, prepare_symbol, regime_series

GAP_GATE = 0.025


# ---------------------------------------------------------------------------
# Build the signal table
# ---------------------------------------------------------------------------

def add_covariates(prepared: pd.DataFrame) -> pd.DataFrame:
    """Attach the entry-time traits a gap might merely be standing in for."""
    out = prepared
    close, volume = out["close"], out["volume"]
    out["atr_pct"] = out["atr"] / close                      # volatility
    out["mom20"] = close / close.shift(20) - 1.0             # recent momentum
    adv_shares = volume.rolling(20, min_periods=20).mean().shift(1)
    out["relvol"] = volume / adv_shares                      # volume surge / catalyst
    out["log_dv"] = np.log(out["adv_dollars"])               # liquidity
    return out


def simulate_signal(prepared: pd.DataFrame, i: int, engine: Backtester) -> tuple[float, int]:
    """Run one signal forward in isolation and return its R multiple and length."""
    bar = prepared.iloc[i]
    entry_price, risk = float(bar["close"]), float(bar["stop_distance"])
    shares = 1000
    position = Position(
        symbol="x", entry_date=prepared.index[i], entry_price=entry_price,
        shares=shares, risk_per_share=risk, stop_price=entry_price - risk,
        initial_shares=shares, initial_risk_dollars=shares * risk,
        highest_high=float(bar["high"]),
    )
    for j in range(i + 1, len(prepared)):
        engine._manage_position(position, prepared.iloc[j], prepared.index[j])
        if position.open_shares == 0:
            return position.realised_pnl / position.initial_risk_dollars, j - i
    if position.open_shares > 0:                              # still open at the end
        engine._close_shares(position, position.open_shares,
                             float(prepared["close"].iloc[-1]), prepared.index[-1], "eot")
    return position.realised_pnl / position.initial_risk_dollars, len(prepared) - 1 - i


def build_signals(cfg: StrategyConfig) -> pd.DataFrame:
    frames = data_mod.load_csv_dir("bars")
    benchmarks = {t: frames.pop(t) for t in ("SPY", "QQQ")}
    regime = regime_series(benchmarks, cfg)
    engine = Backtester(cfg, cost_bps=5.0, commission_per_share=0.005)

    rows = []
    for symbol, frame in frames.items():
        prepared = add_covariates(prepare_symbol(frame, cfg))
        hits = np.flatnonzero(prepared["signal"].to_numpy())
        for i in hits:
            date = prepared.index[i]
            if not bool(regime.get(date, False)):    # same regime gate as the backtest
                continue
            bar = prepared.iloc[i]
            if not np.isfinite([bar["atr_pct"], bar["mom20"], bar["relvol"], bar["log_dv"]]).all():
                continue
            r, held = simulate_signal(prepared, i, engine)
            rows.append({
                "symbol": symbol, "date": date, "r": r, "held": held,
                "gap_pct": float(bar["gap_pct"]), "atr_pct": float(bar["atr_pct"]),
                "mom20": float(bar["mom20"]), "relvol": float(bar["relvol"]),
                "log_dv": float(bar["log_dv"]),
            })

    signals = pd.DataFrame(rows)
    signals["gapper"] = signals["gap_pct"] >= GAP_GATE
    signals["quarter"] = signals["date"].dt.to_period("Q")
    return signals


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def describe(label: str, r: pd.Series) -> str:
    return (f"{label:<34} n={len(r):>5}  win {(r > 0).mean():6.1%}  "
            f"mean {r.mean():+.3f}R  median {r.median():+.3f}R")


def welch(a: pd.Series, b: pd.Series) -> tuple[float, float]:
    diff = b.mean() - a.mean()
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return diff, diff / se if se > 0 else 0.0


def ols(y: np.ndarray, X: np.ndarray, names: list[str]) -> None:
    """Least squares with heteroskedasticity-robust (HC1) standard errors."""
    X = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    meat = (X * resid[:, None] ** 2).T @ X
    cov = XtX_inv @ meat @ XtX_inv * (n / (n - k))
    se = np.sqrt(np.diag(cov))
    print(f"  {'term':<16}{'coef':>10}{'se':>9}{'t':>8}")
    for name, b, s in zip(["intercept"] + names, beta, se):
        print(f"  {name:<16}{b:>10.4f}{s:>9.4f}{b / s:>8.2f}")


def main() -> None:
    cfg = StrategyConfig(name="signal_study")
    print("building signal table (every breakout, unlimited capacity)...", flush=True)
    signals = build_signals(cfg)
    signals.to_csv("signal_study.csv", index=False)
    gappers = signals[signals["gapper"]]
    others = signals[~signals["gapper"]]

    print("\n" + "=" * 78)
    print(f"RAW COMPARISON  ({len(signals):,} signals, {len(gappers):,} gapped)")
    print("=" * 78)
    print(describe("gap >= 2.5%", gappers["r"]))
    print(describe("no gap", others["r"]))
    diff, t = welch(others["r"], gappers["r"])
    print(f"\n  difference {diff:+.3f}R, t = {t:.2f}"
          f"  -> {'significant' if abs(t) > 1.96 else 'not significant'} at 5%")

    print("\n" + "=" * 78)
    print("WHAT ELSE IS DIFFERENT ABOUT GAPPERS?")
    print("=" * 78)
    print(f"  {'trait':<12}{'gappers':>12}{'non-gappers':>14}{'ratio':>9}")
    for trait in ("atr_pct", "mom20", "relvol", "log_dv"):
        g, o = gappers[trait].median(), others[trait].median()
        print(f"  {trait:<12}{g:>12.4f}{o:>14.4f}{g / o if o else float('nan'):>9.2f}")

    # -- Stratified: hold each confounder roughly constant --------------------
    for trait in ("atr_pct", "relvol", "mom20"):
        print("\n" + "=" * 78)
        print(f"WITHIN QUINTILES OF {trait.upper()}  (holding it roughly constant)")
        print("=" * 78)
        buckets = pd.qcut(signals[trait], 5, labels=False, duplicates="drop")
        print(f"  {'quintile':<10}{'n_gap':>7}{'n_other':>9}{'gap meanR':>12}"
              f"{'other meanR':>13}{'diff':>9}{'t':>7}")
        for q in sorted(pd.Series(buckets).dropna().unique()):
            sub = signals[buckets == q]
            a, b = sub.loc[~sub["gapper"], "r"], sub.loc[sub["gapper"], "r"]
            if len(a) < 20 or len(b) < 20:
                continue
            d, tstat = welch(a, b)
            print(f"  Q{int(q) + 1:<9}{len(b):>7}{len(a):>9}{b.mean():>12.3f}"
                  f"{a.mean():>13.3f}{d:>9.3f}{tstat:>7.2f}")

    # -- Nearest-neighbour matching ------------------------------------------
    print("\n" + "=" * 78)
    print("MATCHED CONTROLS")
    print("=" * 78)
    print("Each gapper paired with the non-gapper in the same calendar quarter")
    print("closest on volatility, momentum, relative volume and liquidity.\n")

    traits = ["atr_pct", "mom20", "relvol", "log_dv"]
    z = (signals[traits] - signals[traits].mean()) / signals[traits].std()
    pairs = []
    for quarter, group in signals.groupby("quarter"):
        idx_g = group.index[group["gapper"]]
        idx_o = group.index[~group["gapper"]]
        if len(idx_g) == 0 or len(idx_o) == 0:
            continue
        ctrl = z.loc[idx_o].to_numpy()
        for gi in idx_g:
            dist = np.linalg.norm(ctrl - z.loc[gi].to_numpy(), axis=1)
            best = idx_o[int(np.argmin(dist))]
            pairs.append({"gap_r": signals.at[gi, "r"], "ctrl_r": signals.at[best, "r"],
                          "ctrl": best, "dist": float(dist.min())})

    matched = pd.DataFrame(pairs)
    print(describe("gappers", matched["gap_r"]))
    print(describe("matched non-gappers", matched["ctrl_r"]))
    print(f"  ({matched['ctrl'].nunique()} distinct controls used, "
          f"median match distance {matched['dist'].median():.3f} sd)")
    paired = matched["gap_r"] - matched["ctrl_r"]
    t_paired = paired.mean() / (paired.std(ddof=1) / np.sqrt(len(paired)))
    print(f"\n  paired difference {paired.mean():+.3f}R, t = {t_paired:.2f}"
          f"  -> {'significant' if abs(t_paired) > 1.96 else 'not significant'} at 5%")

    # -- Regression: does gap survive with the confounders in the model? ------
    print("\n" + "=" * 78)
    print("REGRESSION  r ~ gap + volatility + momentum + volume surge + liquidity")
    print("=" * 78)
    X = signals[["gapper", "atr_pct", "mom20", "relvol", "log_dv"]].astype(float).to_numpy()
    ols(signals["r"].to_numpy(), X, ["gap(0/1)", "atr_pct", "mom20", "relvol", "log_dv"])

    print("\n  same model, gap as a continuous size rather than a switch:")
    X2 = signals[["gap_pct", "atr_pct", "mom20", "relvol", "log_dv"]].astype(float).to_numpy()
    ols(signals["r"].to_numpy(), X2, ["gap_pct", "atr_pct", "mom20", "relvol", "log_dv"])

    # -- Head-to-head: gap vs the volume surge -------------------------------
    print("\n" + "=" * 78)
    print("HEAD-TO-HEAD: GAP GATE vs VOLUME-SURGE GATE")
    print("=" * 78)
    print("Both gates keep a similar share of signals; which one earns more?\n")
    keep = len(gappers) / len(signals)
    relvol_cut = signals["relvol"].quantile(1 - keep)
    atr_cut = signals["atr_pct"].quantile(1 - keep)
    print(describe(f"gap >= {GAP_GATE:.1%}", gappers["r"]))
    print(describe(f"relvol >= {relvol_cut:.2f}", signals.loc[signals["relvol"] >= relvol_cut, "r"]))
    print(describe(f"atr_pct >= {atr_cut:.3f}", signals.loc[signals["atr_pct"] >= atr_cut, "r"]))
    print(describe("all signals", signals["r"]))


if __name__ == "__main__":
    main()
