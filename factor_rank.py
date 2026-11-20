"""CLI: score and rank a pool of stocks with price-based factors.

Example:
  python factor_rank.py
  python factor_rank.py --tickers AAPL MSFT NVDA AMZN GOOGL META

The default pool is a fixed demo universe of 20 large-cap US stocks,
chosen for sector diversity in a lesson — it is NOT a recommendation
list. Scores are relative *within the pool you pass in*: the same stock
scores differently in a different pool.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

import pandas as pd

from data import load_prices
from factors import compute_factors, score_factors

RESULTS = pathlib.Path(__file__).parent / "results"

DEFAULT_POOL = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "LLY",
    "JPM", "V", "MA", "UNH", "XOM", "HD", "COST", "WMT",
    "PG", "JNJ", "CRM", "NFLX",
]


def main() -> None:
    ap = argparse.ArgumentParser(description="Price-factor ranking")
    ap.add_argument("--tickers", nargs="+", default=DEFAULT_POOL)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    prices = load_prices(args.tickers, start=args.start, refresh=args.refresh)
    missing = [t for t in args.tickers if t not in prices.columns or prices[t].dropna().empty]
    if missing:
        print(f"警告: 以下标的无数据, 已剔除: {missing}")
    prices = prices.drop(columns=missing).dropna(how="all")
    prices = prices.ffill().dropna()

    factors = compute_factors(prices)
    ranked = score_factors(factors)
    as_of = pd.Timestamp(ranked["as_of"].iloc[0]).date()
    print(f"因子排名 (数据截至 {as_of}, 池内 {len(ranked)} 只, 分数是池内相对排名)\n")
    header = (f"{'#':>3} {'代码':<6}{'综合分':>7}{'动量12-1':>10}{'动量6M':>9}"
              f"{'动量3M':>9}{'年化波动':>10}{'距52周高点':>11}")
    print(header)
    print("-" * len(header))
    for i, (ticker, r) in enumerate(ranked.iterrows(), 1):
        print(f"{i:>3} {ticker:<6}{r['composite']:>7.1f}{r['momentum_12_1']:>10.1%}"
              f"{r['momentum_6m']:>9.1%}{r['momentum_3m']:>9.1%}"
              f"{r['volatility_3m']:>10.1%}{r['dist_52w_high']:>11.1%}")

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "factor_rank_latest.csv"
    ranked.to_csv(out)
    print(f"\n明细已保存: {out}")
    print("说明: 综合分 = 各因子池内百分位排名的加权平均 x100 (权重见 src/factors.py)。")
    print("本版只有价格类因子; 价值 (PE/PB/FCF收益率) 与质量 (ROE/利润率/杠杆) 需要财报数据, 尚未接入。")


if __name__ == "__main__":
    main()
