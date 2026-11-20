"""Download and cache daily prices.

Primary source: Nasdaq's public historical API (no key needed).
Fallback: Yahoo Finance via yfinance, if installed and reachable.

Note: Nasdaq closes are split-adjusted but not dividend-adjusted, so
long-horizon total returns are slightly understated vs. total-return
indices. Fine for strategy comparison; noted in the README.
"""
from __future__ import annotations

import io
import json
import pathlib
import urllib.request

import pandas as pd

CACHE_DIR = pathlib.Path(__file__).resolve().parent.parent / "data_cache"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}


def _nasdaq_close(ticker: str, start: str) -> pd.Series:
    fromdate = pd.Timestamp(start).strftime("%Y-%m-%d")
    last_err: Exception | None = None
    for assetclass in ("etf", "stocks"):
        url = (f"https://api.nasdaq.com/api/quote/{ticker}/historical"
               f"?assetclass={assetclass}&fromdate={fromdate}&limit=99999")
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            rows = payload["data"]["tradesTable"]["rows"]
            s = pd.Series(
                {pd.Timestamp(r["date"]): float(r["close"].replace(",", "").replace("$", ""))
                 for r in rows},
                name=ticker,
            ).sort_index()
            if len(s) > 50:
                return s
        except Exception as e:  # try the other asset class
            last_err = e
    raise RuntimeError(f"Nasdaq download failed for {ticker}: {last_err}")


def _yahoo_close(tickers: list[str], start: str, end: str | None) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(tickers, start=start, end=end, auto_adjust=True,
                      progress=False, threads=True)
    prices = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    if isinstance(prices, pd.Series):
        prices = prices.to_frame(tickers[0])
    return prices


def load_prices(tickers: list[str], start: str = "2016-01-01", end: str | None = None,
                refresh: bool = False) -> pd.DataFrame:
    """Return a DataFrame of daily close prices: index=date, columns=tickers."""
    CACHE_DIR.mkdir(exist_ok=True)
    key = "_".join(sorted(tickers)) + f"_{start}_{end or 'now'}"
    cache_file = CACHE_DIR / f"{key}.csv"
    if cache_file.exists() and not refresh:
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)

    try:
        frame = pd.DataFrame({t: _nasdaq_close(t, start) for t in tickers})
    except Exception:
        frame = _yahoo_close(tickers, start, end)
    if end:
        frame = frame.loc[:end]
    frame = frame.dropna(how="all").ffill()
    frame.to_csv(cache_file)
    return frame
