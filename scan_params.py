"""Parameter sensitivity scan for the SMA trend strategy.

Lesson goals:
1. A robust strategy works across a *plateau* of parameters, not one magic pair.
2. Picking the best in-sample parameters and trusting them is overfitting:
   compare the in-sample winner's out-of-sample result with the median.

Usage:
  python scan_params.py --ticker SPY
  python scan_params.py --ticker QQQ --split 2022-01-01
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from backtest import buy_and_hold, run_backtest
from data import load_prices
from metrics import summarize
import strategies

RESULTS = pathlib.Path(__file__).parent / "results"
FASTS = [10, 20, 30, 50, 75, 100]
SLOWS = [100, 150, 200, 250, 300]


def evaluate(prices: pd.DataFrame, weights: pd.DataFrame, start, end) -> dict:
    p = prices.loc[start:end]
    w = weights.loc[start:end]
    eq = run_backtest(p, w)
    return summarize(eq.astype(float), "x")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="SPY")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--split", default="2022-01-01", help="in/out-of-sample split date")
    args = ap.parse_args()

    prices = load_prices([args.ticker], start=args.start)[[args.ticker]].dropna()
    print(f"{args.ticker}: {prices.index[0].date()} ~ {prices.index[-1].date()}, {len(prices)} 天")
    split = pd.Timestamp(args.split)

    rows = []
    for fast in FASTS:
        for slow in SLOWS:
            if fast >= slow:
                continue
            w = strategies.sma_trend(prices, fast=fast, slow=slow)
            full = evaluate(prices, w, prices.index[0], prices.index[-1])
            ins = evaluate(prices, w, prices.index[0], split)
            oos = evaluate(prices, w, split, prices.index[-1])
            rows.append({"fast": fast, "slow": slow,
                         "full_sharpe": full["sharpe"], "full_cagr": full["cagr"],
                         "full_dd": full["max_drawdown"],
                         "in_sharpe": ins["sharpe"], "in_cagr": ins["cagr"],
                         "oos_sharpe": oos["sharpe"], "oos_cagr": oos["cagr"],
                         "oos_dd": oos["max_drawdown"]})
    df = pd.DataFrame(rows)
    RESULTS.mkdir(exist_ok=True)
    csv_path = RESULTS / f"param_scan_{args.ticker}.csv"
    df.to_csv(csv_path, index=False)

    bench_full = summarize(buy_and_hold(prices, [args.ticker]).astype(float), "bh")
    bench_oos = summarize(buy_and_hold(prices.loc[split:], [args.ticker]).astype(float), "bh")
    print(f"\n基准买入持有: 全期年化 {bench_full['cagr']:.1%} 夏普 {bench_full['sharpe']:.2f} | "
          f"样本外年化 {bench_oos['cagr']:.1%} 夏普 {bench_oos['sharpe']:.2f}")

    print("\n== 全期夏普 Top 5 ==")
    for _, r in df.nlargest(5, "full_sharpe").iterrows():
        print(f"  fast={int(r.fast):>3} slow={int(r.slow):>3}  年化 {r.full_cagr:6.1%}  夏普 {r.full_sharpe:.2f}  最大回撤 {r.full_dd:.1%}")
    print("\n== 全期夏普 Bottom 5 ==")
    for _, r in df.nsmallest(5, "full_sharpe").iterrows():
        print(f"  fast={int(r.fast):>3} slow={int(r.slow):>3}  年化 {r.full_cagr:6.1%}  夏普 {r.full_sharpe:.2f}  最大回撤 {r.full_dd:.1%}")

    best_in = df.loc[df["in_sharpe"].idxmax()]
    print(f"\n== 过拟合演示 ==")
    print(f"样本内最优: fast={int(best_in.fast)} slow={int(best_in.slow)} "
          f"(样本内夏普 {best_in.in_sharpe:.2f}) -> 样本外夏普 {best_in.oos_sharpe:.2f}, 年化 {best_in.oos_cagr:.1%}")
    print(f"样本外夏普中位数: {df['oos_sharpe'].median():.2f}；全期夏普中位数: {df['full_sharpe'].median():.2f}")
    print(f"全部 {len(df)} 组参数中, 全期跑赢基准夏普的有 {(df['full_sharpe'] > bench_full['sharpe']).sum()} 组")

    pivot = df.pivot(index="fast", columns="slow", values="full_sharpe")
    fig, ax = plt.subplots(figsize=(8, 5))
    im = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(len(pivot.columns)), pivot.columns)
    ax.set_yticks(range(len(pivot.index)), pivot.index)
    ax.set_xlabel("slow"); ax.set_ylabel("fast")
    ax.set_title(f"{args.ticker} SMA trend - full-period Sharpe by (fast, slow)")
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            ax.text(j, i, f"{pivot.values[i, j]:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    png = RESULTS / f"param_scan_{args.ticker}.png"
    fig.savefig(png, dpi=120)
    print(f"\n明细: {csv_path}\n热力图: {png}")


if __name__ == "__main__":
    main()
