"""CLI: run the dual-SMA strategy once against an IBKR *paper* account.

Default is DRY-RUN: it computes today's signal from cached/Nasdaq daily
closes, sizes the order in whole shares, prints what it *would* do, and
appends a row to results/paper_log.csv. Nothing connects, nothing orders.

With --execute it connects to a running TWS / IB Gateway paper session
(see README "模拟盘" section), re-verifies the account is a paper (DU)
account, reads the current position, and places at most one market order
to move to the target position.

Examples:
  # dry-run, $10,000 virtual sleeve, Gateway paper port
  python run_paper.py --ticker SPY --budget 10000

  # see what a $100 sleeve would do (whole shares only -> likely 0)
  python run_paper.py --ticker SPY --budget 100

  # real paper execution (Gateway must be running, logged into paper)
  python run_paper.py --ticker SPY --budget 10000 --port 4002 --execute
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

from data import load_prices
import paper_ibkr as p

RESULTS = pathlib.Path(__file__).parent / "results"
LOG = RESULTS / "paper_log.csv"


def append_log(row: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    exists = LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not exists:
            w.writeheader()
        w.writerow(row)


def main() -> None:
    ap = argparse.ArgumentParser(description="IBKR paper-trading runner (paper only)")
    ap.add_argument("--ticker", default="SPY")
    ap.add_argument("--fast", type=int, default=50)
    ap.add_argument("--slow", type=int, default=200)
    ap.add_argument("--budget", type=float, default=10_000,
                    help="virtual sleeve size in USD; position sizing uses this, "
                         "not the paper account's full balance")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4002,
                    help="4002 = IB Gateway paper, 7497 = TWS paper (live ports are refused)")
    ap.add_argument("--client-id", type=int, default=11)
    ap.add_argument("--execute", action="store_true",
                    help="actually connect and order on the paper account (default: dry-run)")
    ap.add_argument("--refresh", action="store_true", help="ignore price cache")
    args = ap.parse_args()

    # Safety check runs even in dry-run, so a typo'd live port fails fast.
    p.assert_paper_endpoint(args.port)

    prices = load_prices([args.ticker], refresh=args.refresh)
    sig = p.latest_signal(prices[args.ticker], fast=args.fast, slow=args.slow)
    target_qty = p.whole_share_qty(args.budget, sig["close"]) if sig["hold"] else 0

    print(f"标的 {args.ticker}  数据截至 {sig['date'].date()}")
    print(f"收盘 {sig['close']:.2f}  SMA{args.fast} {sig['sma_fast']:.2f}  "
          f"SMA{args.slow} {sig['sma_slow']:.2f}  -> 信号: "
          f"{'持有' if sig['hold'] else '空仓'}")
    print(f"虚拟资金池 ${args.budget:,.0f}，整股数量 -> 目标持仓 {target_qty} 股"
          f"（IBKR API 不支持碎股）")
    if sig["hold"] and target_qty == 0:
        print("注意: 预算不够买 1 整股，目标为 0 股 — 这正是 $100 + 高价标的"
              "在 IBKR API 下的真实约束。")

    mode = "dry-run"
    current_qty = 0
    plan = p.plan_order(current_qty, target_qty)

    if args.execute:
        ib, accounts = p.connect_ibkr(args.host, args.port, args.client_id)
        account = accounts[0]
        current_qty = p.current_position(ib, args.ticker)
        plan = p.plan_order(current_qty, target_qty)
        print(f"已连接模拟账户 {account}，当前持仓 {current_qty} 股，"
              f"计划: {plan['action']} {plan['qty']} 股")
        trade = p.place_paper_order(ib, args.ticker, plan, account)
        mode = "paper-executed" if trade is not None else "paper-noop"
        if trade is not None:
            ib.sleep(2)
            print(f"订单状态: {trade.orderStatus.status}")
        ib.disconnect()
    else:
        print(f"[dry-run] 假设当前 0 股，计划: {plan['action']} {plan['qty']} 股。"
              "未连接券商、未下单。")

    append_log({
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "ticker": args.ticker,
        "data_date": sig["date"].date(),
        "close": round(sig["close"], 2),
        "sma_fast": round(sig["sma_fast"], 2),
        "sma_slow": round(sig["sma_slow"], 2),
        "hold": sig["hold"],
        "budget": args.budget,
        "current_qty": current_qty,
        "target_qty": target_qty,
        "action": plan["action"],
        "order_qty": plan["qty"],
    })
    print(f"已记录到 {LOG}")


if __name__ == "__main__":
    main()
