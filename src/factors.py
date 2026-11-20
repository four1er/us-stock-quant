"""Cross-sectional factors computed from prices only.

A *factor* is a measurable characteristic that (a) can be computed the
same way for every stock, and (b) is used to rank stocks against each
other at one point in time (cross-section), instead of timing a single
asset over time.

This module implements the factors that prices alone can support:

- momentum_12_1 : return from 12 months ago to 1 month ago.
  The most recent month is skipped on purpose: very short-term returns
  tend to *reverse*, long-term momentum tends to *persist*.
- momentum_6m / momentum_3m : plain 6-month / 3-month returns.
- volatility_3m : annualised volatility of daily returns, last 3 months.
  Scored inversely (lower volatility = higher score): the low-volatility
  anomaly says calmer stocks have historically not been penalised in
  return for their lower risk.
- dist_52w_high : close / highest close of the last 252 trading days - 1.
  Always <= 0; closer to 0 means the price sits near its 52-week high,
  which empirically carries momentum information (George & Hwang, 2004).

Value (P/E, P/B, FCF yield) and quality (ROE, margins, leverage) factors
need financial statements and are NOT here yet — see README roadmap.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252

# Composite weights. These are a *choice*, not a truth — lesson 2 applies:
# if a ranking flips completely when weights move a little, don't trust it.
WEIGHTS = {
    "momentum_12_1": 0.30,
    "momentum_6m": 0.20,
    "momentum_3m": 0.15,
    "dist_52w_high": 0.20,
    "low_volatility": 0.15,
}


def compute_factors(prices: pd.DataFrame) -> pd.DataFrame:
    """Raw factor values per ticker, from the last available trading day."""
    prices = prices.ffill()
    if len(prices) < 253:
        raise ValueError(f"need at least 253 trading days, got {len(prices)}")
    last = prices.iloc[-1]
    rets = prices.pct_change()
    out = pd.DataFrame(index=prices.columns)
    out["momentum_12_1"] = prices.iloc[-22] / prices.iloc[-253] - 1
    out["momentum_6m"] = last / prices.iloc[-127] - 1
    out["momentum_3m"] = last / prices.iloc[-64] - 1
    out["volatility_3m"] = rets.tail(63).std() * np.sqrt(TRADING_DAYS)
    out["dist_52w_high"] = last / prices.tail(252).max() - 1
    out["last_close"] = last
    out["as_of"] = prices.index[-1]
    return out


def score_factors(factors: pd.DataFrame) -> pd.DataFrame:
    """Turn raw values into 0-100 cross-sectional scores.

    Each factor is converted to a percentile rank across the pool
    (0 = worst in pool, 1 = best in pool). Percentile ranks are used
    instead of the raw values so that one extreme stock cannot dominate
    the composite, and so factors with different units can be averaged.
    """
    scored = factors.copy()
    scored["s_momentum_12_1"] = factors["momentum_12_1"].rank(pct=True)
    scored["s_momentum_6m"] = factors["momentum_6m"].rank(pct=True)
    scored["s_momentum_3m"] = factors["momentum_3m"].rank(pct=True)
    scored["s_dist_52w_high"] = factors["dist_52w_high"].rank(pct=True)
    # inverse direction: lower volatility scores higher
    scored["s_low_volatility"] = factors["volatility_3m"].rank(pct=True, ascending=False)
    composite = (
        WEIGHTS["momentum_12_1"] * scored["s_momentum_12_1"]
        + WEIGHTS["momentum_6m"] * scored["s_momentum_6m"]
        + WEIGHTS["momentum_3m"] * scored["s_momentum_3m"]
        + WEIGHTS["dist_52w_high"] * scored["s_dist_52w_high"]
        + WEIGHTS["low_volatility"] * scored["s_low_volatility"]
    )
    scored["composite"] = (composite * 100).round(1)
    return scored.sort_values("composite", ascending=False)
