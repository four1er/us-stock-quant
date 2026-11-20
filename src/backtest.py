"""A small vectorized backtest engine.

Design choices that keep the backtest honest:
- Weights are shifted by one day before being applied: the signal you
  compute from today's close can only earn returns from tomorrow.
- Transaction costs are charged on turnover (weight changes), in bps.
- Cash (weights summing to < 1) earns 0%.
"""
from __future__ import annotations

import pandas as pd


def run_backtest(prices: pd.DataFrame, weights: pd.DataFrame,
                 cost_bps: float = 5.0, initial: float = 1.0) -> pd.Series:
    """Return the strategy equity curve (starting at `initial`)."""
    prices = prices.reindex(weights.index).ffill()
    asset_rets = prices.pct_change().fillna(0.0)
    applied = weights.shift(1).fillna(0.0)  # no lookahead: trade at next day
    gross = (applied * asset_rets).sum(axis=1)
    turnover = applied.diff().abs().sum(axis=1).fillna(applied.abs().sum(axis=1))
    costs = turnover * (cost_bps / 10_000)
    net = gross - costs
    equity = initial * (1 + net).cumprod()
    equity.iloc[0] = initial
    return equity


def buy_and_hold(prices: pd.DataFrame, tickers: list[str], initial: float = 1.0) -> pd.Series:
    """Equal-weight buy & hold benchmark over `tickers`."""
    sub = prices[tickers].dropna()
    normed = sub / sub.iloc[0]
    return initial * normed.mean(axis=1)
