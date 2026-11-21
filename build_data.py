"""CLI: build / update the local dataset and print a quality audit.

Examples:
  # first build: full history for a starter universe
  python build_data.py --tickers SPY QQQ IWM EFA EEM TLT GLD AAPL MSFT NVDA

  # daily update: only the last ~10 days are re-fetched and merged
  python build_data.py --tickers SPY QQQ

  # also cross-check raw closes against the Nasdaq source on the overlap
  python build_data.py --tickers SPY --cross-check

Outputs: data_store/ (raw + clean parquet + events + manifest.json)
and results/data_audit.csv. The data itself is git-ignored; the audit
table is the shareable evidence of what the data covers.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

import data_pipeline as dp

RESULTS = pathlib.Path(__file__).parent / "results"


def main() -> None:
    ap = argparse.ArgumentParser(description="Build/update the quant dataset")
    ap.add_argument("--tickers", nargs="+",
                    default=["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD",
                             "AAPL", "MSFT", "NVDA"])
    ap.add_argument("--start", default="1970-01-01",
                    help="earliest date to fetch (sources return from listing)")
    ap.add_argument("--source", choices=["yahoo", "nasdaq"], default="yahoo")
    ap.add_argument("--refresh", action="store_true",
                    help="full re-download instead of incremental update")
    ap.add_argument("--cross-check", action="store_true",
                    help="compare raw closes vs Nasdaq on the overlap window")
    args = ap.parse_args()

    for t in args.tickers:
        entry = dp.build_dataset(t, start=args.start, source=args.source,
                                 refresh=args.refresh)
        print(f"{t:<6} {entry['rows']:>6} 行  {entry['start']} ~ {entry['end']}  "
              f"源={entry['source']} sha={entry['sha256_16']}")

    report = dp.audit(args.tickers)
    RESULTS.mkdir(exist_ok=True)
    report.to_csv(RESULTS / "data_audit.csv", index=False)
    print("\n数据审计（total_return_adj 含分红再投资，raw 不含）:")
    print(report.to_string(index=False))

    if args.cross_check:
        print("\n双源交叉校验（原始收盘价重叠窗口）:")
        for t in args.tickers:
            try:
                y = dp.fetch_yahoo(t, start="2018-01-01")[0]
                n = dp.fetch_nasdaq(t, start="2018-01-01")
                print(f"  {t:<6} {dp.cross_check(t, y, n)}")
            except Exception as e:  # cross-check is best-effort evidence
                print(f"  {t:<6} 校验不可用（免费源不稳定）: {e}")


if __name__ == "__main__":
    main()
