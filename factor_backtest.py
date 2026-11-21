"""CLI: factor strategy backtest — monthly rebalance, hold Top N by composite score.

At each month-end, rank the pool with the same price factors as
factor_rank.py (momentum 12-1 / 6M / 3M, low volatility, distance to
52-week high), hold the Top N equal-weight for the next month, and
compare against SPY buy-and-hold and the equal-weight pool.

Honesty rules (same as the rest of this repo):
- No lookahead: the ranking at a rebalance date uses only prices up
  to that date (compute_factors on the sliced history), and the
  backtest engine shifts weights by one day before applying them.
- Costs: 5 bps charged on turnover by default.
- The pool is a hand-picked 20 large-cap demo universe with
  survivorship bias; this tests the *factor*, not a buy list.

Example:
  python factor_backtest.py                # Top 5, monthly
  python factor_backtest.py --top-n 3
  python factor_backtest.py --top-n 10 --cost-bps 10
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

import pandas as pd

from backtest import buy_and_hold, run_backtest
from data import load_prices
from factors import compute_factors, score_factors
from metrics import format_summary, summarize

RESULTS = pathlib.Path(__file__).parent / "results"

DEFAULT_POOL = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "LLY",
    "JPM", "V", "MA", "UNH", "XOM", "HD", "COST", "WMT",
    "PG", "JNJ", "CRM", "NFLX",
]


def month_end_dates(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """Last trading day of each calendar month in the index."""
    frame = pd.DataFrame(index=index)
    return list(frame.groupby([index.year, index.month]).tail(1).index)


def build_weights(prices: pd.DataFrame, top_n: int) -> tuple[pd.DataFrame, list[dict]]:
    """Monthly Top-N weights; holdings log records each rebalance."""
    weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    holdings: list[dict] = []
    rebalance_dates: list[pd.Timestamp] = []
    picks: list[list[str]] = []
    for date in month_end_dates(prices.index):
        window = prices.loc[:date]
        if len(window) < 253:
            continue
        ranked = score_factors(compute_factors(window))
        top = list(ranked.index[:top_n])
        rebalance_dates.append(date)
        picks.append(top)
        holdings.append({"date": date.date().isoformat(), "top_n": top_n,
                         "holdings": ",".join(top),
                         "top_score": float(ranked["composite"].iloc[0]),
                         "cutoff_score": float(ranked["composite"].iloc[top_n - 1])})
    # Hold each pick from its rebalance close until the next rebalance
    # (exclusive); the engine shifts weights by one day, so no lookahead.
    idx = list(prices.index)
    for i, (date, top) in enumerate(zip(rebalance_dates, picks)):
        start_pos = idx.index(date)
        end_pos = idx.index(rebalance_dates[i + 1]) if i + 1 < len(rebalance_dates) else len(idx)
        weights.iloc[start_pos:end_pos, [list(prices.columns).index(t) for t in top]] = 1.0 / top_n
    return weights, holdings


def main() -> None:
    ap = argparse.ArgumentParser(description="Factor Top-N backtest")
    ap.add_argument("--tickers", nargs="+", default=DEFAULT_POOL)
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    prices = load_prices(args.tickers, start=args.start, refresh=args.refresh)
    prices = prices.dropna(how="all").ffill().dropna()
    spy = load_prices(["SPY"], start=args.start, refresh=args.refresh)["SPY"]
    spy = spy.reindex(prices.index).ffill().dropna()
    common = prices.index.intersection(spy.index)
    prices, spy = prices.loc[common], spy.loc[common]

    weights, holdings = build_weights(prices, args.top_n)
    equity = run_backtest(prices, weights, cost_bps=args.cost_bps)
    # Benchmarks over the same window, starting at the first rebalance.
    first = holdings[0]["date"] if holdings else str(prices.index[0].date())
    start_date = pd.Timestamp(first)
    eq = equity.loc[start_date:]
    spy_eq = buy_and_hold(spy.to_frame("SPY"), ["SPY"]).loc[start_date:]
    spy_eq = spy_eq / spy_eq.iloc[0] * eq.iloc[0]
    pool_eq = buy_and_hold(prices, list(prices.columns)).loc[start_date:]
    pool_eq = pool_eq / pool_eq.iloc[0] * eq.iloc[0]

    rows = [
        summarize(eq, f"因子 Top {args.top_n}"),
        summarize(spy_eq, "SPY 买入持有"),
        summarize(pool_eq, "等权 20 只池"),
    ]
    print(f"因子策略回测 (月度调仓, Top {args.top_n}, 成本 {args.cost_bps} bps)")
    print(f"窗口: {eq.index[0].date()} 至 {eq.index[-1].date()}, 调仓 {len(holdings)} 次")
    print(f"价格截至 {prices.index[-1].date()}, 池内 {len(prices.columns)} 只\n")
    print(format_summary(rows))
    print("\n最近 5 次调仓:")
    for h in holdings[-5:]:
        print(f"  {h['date']}: {h['holdings']} (截断分 {h['cutoff_score']:.1f})")

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"factor_backtest_top{args.top_n}.csv"
    pd.DataFrame({"factor_top_n": eq, "spy": spy_eq, "equal_weight_pool": pool_eq}).to_csv(out)
    pd.DataFrame(holdings).to_csv(RESULTS / f"factor_holdings_top{args.top_n}.csv", index=False)
    print(f"\n净值曲线已保存: {out}")
    print("说明: 分数是池内相对值; 池为手工挑的 20 只现存大盘股, 有幸存者偏差;")
    print("本版只有价格类因子, 未接入财报的价值/质量因子。")


if __name__ == "__main__":
    main()
