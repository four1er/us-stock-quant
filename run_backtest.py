"""CLI: run a strategy backtest and compare it with buy & hold.

Examples:
  python run_backtest.py --strategy sma --tickers SPY
  python run_backtest.py --strategy momentum --tickers SPY QQQ IWM EFA EEM TLT GLD
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backtest import buy_and_hold, run_backtest
from data import load_prices
from metrics import format_summary, summarize
import strategies

RESULTS = pathlib.Path(__file__).parent / "results"


def main() -> None:
    ap = argparse.ArgumentParser(description="US stock strategy backtester")
    ap.add_argument("--strategy", choices=["sma", "momentum"], default="sma")
    ap.add_argument("--tickers", nargs="+", default=["SPY"])
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--cost-bps", type=float, default=5.0, help="one-way cost in bps")
    ap.add_argument("--fast", type=int, default=50)
    ap.add_argument("--slow", type=int, default=200)
    ap.add_argument("--lookback", type=int, default=126)
    ap.add_argument("--top-n", type=int, default=3)
    ap.add_argument("--refresh", action="store_true", help="ignore price cache")
    args = ap.parse_args()

    prices = load_prices(args.tickers, start=args.start, refresh=args.refresh)
    prices = prices.dropna()
    print(f"数据: {list(prices.columns)}  {prices.index[0].date()} ~ {prices.index[-1].date()}  共 {len(prices)} 个交易日")

    if args.strategy == "sma":
        weights = strategies.sma_trend(prices, fast=args.fast, slow=args.slow)
        label = f"SMA趋势({args.fast}/{args.slow})"
    else:
        weights = strategies.momentum_rotation(prices, lookback=args.lookback, top_n=args.top_n)
        label = f"动量轮动(lb={args.lookback},top{args.top_n})"

    equity = run_backtest(prices, weights, cost_bps=args.cost_bps)
    bench = buy_and_hold(prices, list(prices.columns))
    common = equity.index.intersection(bench.index)
    equity, bench = equity[common].astype(float), bench[common].astype(float)

    rows = [summarize(equity, label), summarize(bench, "买入持有(基准)")]
    print(format_summary(rows))

    RESULTS.mkdir(exist_ok=True)
    tag = f"{args.strategy}_{'-'.join(args.tickers)}".replace('/', '_')
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(equity, label="Strategy")
    axes[0].plot(bench, label="Buy & Hold", alpha=0.7)
    axes[0].set_yscale("log")
    axes[0].set_title(f"{args.strategy} vs Buy & Hold (log scale)")
    axes[0].legend(); axes[0].grid(True, alpha=0.3)
    dd = equity / equity.cummax() - 1
    axes[1].fill_between(dd.index, dd, color="red", alpha=0.4)
    axes[1].set_title("Drawdown")
    axes[1].grid(True, alpha=0.3)
    fig.tight_layout()
    out = RESULTS / f"{tag}.png"
    fig.savefig(out, dpi=120)
    print(f"图表已保存: {out}")


if __name__ == "__main__":
    main()
