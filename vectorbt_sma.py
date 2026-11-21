"""Lesson: replicate the dual-SMA strategy in vectorbt and reconcile
it against our hand-written engine, line by line.

Reconciliation discipline — everything that can be held equal IS held
equal, so any remaining difference is pure engine mechanics:
  * same data: data_store adj_close (total-return prices) via the
    data pipeline, same windows;
  * same signal: fast SMA > slow SMA state, computed with pandas
    rolling exactly like src/strategies.sma_trend;
  * same cost: 5 bps one-way (vectorbt `fees=0.0005` per order);
  * same metrics: BOTH equity curves are fed through
    src/metrics.summarize, so Sharpe/drawdown formulas cannot differ.

Known mechanical differences to look for in the output:
  1. Fill timing: our engine applies the weight from the *next* day's
     return (equivalent to buying at today's close). vectorbt's
     from_signals also fills at the signal bar's close by default.
     These should agree — if they don't, a default differs.
  2. Fee base: ours charges turnover x equity (via return deduction);
     vectorbt charges fees on the actual order notional.
  3. Sizing: ours is a continuous weight (implicitly rebalanced daily,
     fractional). vectorbt buys once with all cash and holds real
     (fractional) shares — no daily rebalancing to a target weight.

Findings from the first reconciliation run (SPY 50/200, adj_close):
  * Equity curves agree to 0.03pp over 33 years (1910.69% vs 1910.72%),
    trade counts identical (31). The engines are mechanically equivalent
    for this strategy; the residual is the fee-base difference in (2).
  * TRAP 1 — vectorbt's native pf.sharpe_ratio() is NOT our Sharpe:
    it annualises with 365 calendar days, we (and the industry) use 252
    trading days. Same curve: 0.864 native vs 0.718 ours, a factor of
    exactly sqrt(365/252) = 1.203. Always check the annualisation
    before comparing Sharpe numbers across frameworks.
  * TRAP 2 — vbt.MA.run(close, fasts) x MA.run(close, slows) crossing
    pairs windows element-wise (zip), it does NOT build the full grid:
    [5,10,20,30,50] x [60,100,150,200,250] silently runs only the 5
    pairs (5,60),(10,100),... And multi-column from_signals shares one
    cash pool by default, so column results differ from single runs.
    Parameter scans must be built combo-by-combo (or with explicit
    grouping), never trusted from a naive broadcast.

Usage:
  python vectorbt_sma.py                 # SPY, 50/200, both windows
  python vectorbt_sma.py --ticker QQQ --fast 10 --slow 100
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

import pandas as pd

import data_pipeline as dp
from backtest import run_backtest
from metrics import summarize
from strategies import sma_trend

RESULTS = pathlib.Path(__file__).parent / "results"


def self_engine(close: pd.Series, fast: int, slow: int, cost_bps: float) -> tuple[pd.Series, int]:
    prices = close.to_frame("X")
    weights = sma_trend(prices, fast=fast, slow=slow)
    equity = run_backtest(prices, weights, cost_bps=cost_bps)
    n_trades = int((weights["X"].diff().abs() > 0).sum())
    return equity, n_trades


def vbt_engine(close: pd.Series, fast: int, slow: int, fees: float):
    import vectorbt as vbt

    fast_ma = close.rolling(fast).mean()
    slow_ma = close.rolling(slow).mean()
    state = (fast_ma > slow_ma).fillna(False)
    entries = state & ~state.shift(1, fill_value=False)
    exits = ~state & state.shift(1, fill_value=False)
    pf = vbt.Portfolio.from_signals(
        close, entries, exits,
        init_cash=10_000.0, fees=fees, freq="1D",
    )
    equity = pf.value() / 10_000.0
    return equity, int(pf.orders.count()), pf


def reconcile(close: pd.Series, label: str, fast: int, slow: int,
              cost_bps: float) -> list[dict]:
    close = close.dropna()
    eq_self, n_self = self_engine(close, fast, slow, cost_bps)
    t0 = time.time()
    eq_vbt, n_vbt, pf = vbt_engine(close, fast, slow, cost_bps / 10_000)
    vbt_seconds = time.time() - t0
    print(f"  （参考）vectorbt 原生 sharpe_ratio = {float(pf.sharpe_ratio()):.3f}"
          f" — 与下表夏普差 sqrt(365/252)，是年化口径不同，见脚本头 TRAP 1）")
    common = eq_self.index.intersection(eq_vbt.index)
    rows = []
    for name, eq, n in (("自写引擎", eq_self, n_self), ("vectorbt", eq_vbt, n_vbt)):
        s = summarize(eq[common], name)
        rows.append({"window": label, "engine": name,
                     "total_return_%": round(s["total_return"] * 100, 2),
                     "cagr_%": round(s["cagr"] * 100, 2),
                     "sharpe": round(s["sharpe"], 3),
                     "max_drawdown_%": round(s["max_drawdown"] * 100, 2),
                     "n_trades": n})
    gap = abs(rows[0]["total_return_%"] - rows[1]["total_return_%"])
    print(f"\n[{label}] {close.index[0].date()} ~ {close.index[-1].date()} "
          f"共 {len(close)} 天 | vectorbt 耗时 {vbt_seconds:.1f}s（含 numba 编译）")
    for r in rows:
        print(f"  {r['engine']:<10} 总收益 {r['total_return_%']:>9.2f}%  "
              f"年化 {r['cagr_%']:>6.2f}%  夏普 {r['sharpe']:.3f}  "
              f"最大回撤 {r['max_drawdown_%']:>7.2f}%  交易 {r['n_trades']} 次")
    print(f"  -> 总收益差 {gap:.2f} 个百分点")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="vectorbt vs self-engine reconciliation")
    ap.add_argument("--ticker", default="SPY")
    ap.add_argument("--fast", type=int, default=50)
    ap.add_argument("--slow", type=int, default=200)
    ap.add_argument("--cost-bps", type=float, default=5.0)
    args = ap.parse_args()

    adj = dp.load_adj_close([args.ticker])[args.ticker]
    all_rows = []
    all_rows += reconcile(adj, f"{args.ticker} 全历史（复权）",
                          args.fast, args.slow, args.cost_bps)
    recent = adj.loc["2016-11-21":]
    all_rows += reconcile(recent, f"{args.ticker} 近10年（复权）",
                          args.fast, args.slow, args.cost_bps)

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "vectorbt_recon.csv"
    pd.DataFrame(all_rows).to_csv(out, index=False)
    print(f"\n对账表已存 {out}")


if __name__ == "__main__":
    main()
