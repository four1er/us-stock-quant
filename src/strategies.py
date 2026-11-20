"""Trading strategies.

A strategy maps a price DataFrame to *target weights* per asset per day
(rows sum to <= 1; the remainder is cash earning 0%).

IMPORTANT anti-lookahead rule: weights decided from data up to day t are
executed by the engine starting day t+1 (the engine shifts weights by one
day), so a strategy may use same-day close information freely.
"""
from __future__ import annotations

import pandas as pd


def sma_trend(prices: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.DataFrame:
    """Trend filter per asset: hold the asset while its fast SMA > slow SMA,
    otherwise sit in cash. With several assets, held assets share weight equally."""
    fast_ma = prices.rolling(fast).mean()
    slow_ma = prices.rolling(slow).mean()
    signal = (fast_ma > slow_ma).astype(float)
    counts = signal.sum(axis=1).replace(0, pd.NA)
    weights = signal.div(counts, axis=0).fillna(0.0)
    return weights


def momentum_rotation(prices: pd.DataFrame, lookback: int = 126, top_n: int = 3,
                      trend_slow: int = 200) -> pd.DataFrame:
    """Cross-sectional momentum: every day, rank assets by past `lookback`-day
    return, hold the top `top_n` equally — but only while each is above its
    own long-term trend (slow SMA); others stay in cash."""
    momentum = prices / prices.shift(lookback) - 1
    trend_ok = prices > prices.rolling(trend_slow).mean()
    ranks = momentum.rank(axis=1, ascending=False, method="first")
    selected = ((ranks <= top_n) & trend_ok).astype(float)
    counts = selected.sum(axis=1).replace(0, pd.NA)
    weights = selected.div(counts, axis=0).fillna(0.0)
    return weights
