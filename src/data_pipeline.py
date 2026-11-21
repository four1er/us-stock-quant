"""Data pipeline v1: multi-source download -> clean -> validate -> store.

Why this exists (the old src/data.py was a *cache*, not a pipeline):
- it kept only the close column and threw OHLCV away;
- its source (Nasdaq API) is split-adjusted but NOT dividend-adjusted,
  and only reaches back ~10 years;
- there was no validation, no manifest, no record of where data came
  from or when it was fetched.

Pipeline layout (data_store/, git-ignored):
  raw/<TICKER>_<source>.csv     parsed response, kept as fetched
  clean/<TICKER>.parquet        date-indexed OHLCV + adj_close + adj_factor
  events/<TICKER>_events.csv    dividends and splits (from Yahoo events)
  manifest.json                 per-dataset provenance: source, fetched_at,
                                rows, date range, sha256 of the clean file

Primary source: Yahoo Finance chart API (unofficial but public).
It is the only free source we found that gives, in one call:
  * full history back to listing (SPY 1993, AAPL 1980),
  * OHLCV, *and* adjclose (split+dividend adjusted), *and* div/split events.
Cross-check source: Nasdaq public API (raw OHLCV, ~10y). On the overlap
window the two sources' raw closes must agree to ~0; a systematic gap
means one of them changed methodology and results need re-checking.

Storage note: parquet via pyarrow. Pin pyarrow<19 if your numpy is 1.x
(pyarrow>=19 needs numpy>=2); requirements.txt carries the pin.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import time
import urllib.request

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
STORE = ROOT / "data_store"
RAW = STORE / "raw"
CLEAN = STORE / "clean"
EVENTS = STORE / "events"
MANIFEST = STORE / "manifest.json"

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


def _get_json(url: str, headers: dict | None = None, timeout: int = 60,
              allow_empty: bool = False) -> dict:
    """GET JSON with up to 3 attempts on transport errors. Free public
    APIs drop requests transiently, so a pipeline must retry before
    declaring failure. With allow_empty=True an API-level 'no data'
    payload is returned for the caller to interpret (Nasdaq uses it to
    say 'wrong asset class', which is a signal, not a failure)."""
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={**_UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if not allow_empty and isinstance(payload, dict) \
                    and payload.get("data") is None and "chart" not in payload:
                raise RuntimeError(f"empty data payload: {str(payload)[:120]}")
            return payload
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET failed after 3 attempts: {url[:80]}... ({last_err})")


# ---------------------------------------------------------------- sources

def fetch_yahoo(ticker: str, start: str = "1970-01-01",
                end: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily OHLCV + adj_close from the Yahoo chart API, plus div/split events."""
    p1 = int(pd.Timestamp(start, tz="UTC").timestamp())
    end_ts = pd.Timestamp(end, tz="UTC") if end else pd.Timestamp.now(tz="UTC")
    p2 = int((end_ts + pd.Timedelta(days=1)).timestamp())
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div,split")
    payload = _get_json(url)
    result = payload["chart"]["result"][0]
    ts = pd.to_datetime(result["timestamp"], unit="s", utc=True) \
           .tz_convert("America/New_York").normalize().tz_localize(None)
    q = result["indicators"]["quote"][0]
    df = pd.DataFrame({
        "open": q["open"], "high": q["high"], "low": q["low"],
        "close": q["close"], "volume": q["volume"],
    }, index=ts)
    adj = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
    df["adj_close"] = adj if adj is not None else np.nan

    events = []
    ev = result.get("events") or {}
    for item in (ev.get("dividends") or {}).values():
        events.append({"date": pd.to_datetime(item["date"], unit="s", utc=True)
                       .tz_convert("America/New_York").normalize().tz_localize(None),
                       "type": "dividend", "value": item["amount"]})
    for item in (ev.get("splits") or {}).values():
        events.append({"date": pd.to_datetime(item["date"], unit="s", utc=True)
                       .tz_convert("America/New_York").normalize().tz_localize(None),
                       "type": "split",
                       "value": item["numerator"] / item["denominator"]})
    ev_df = pd.DataFrame(events, columns=["date", "type", "value"]) \
        .sort_values("date").reset_index(drop=True) if events else \
        pd.DataFrame(columns=["date", "type", "value"])
    return df, ev_df


def fetch_nasdaq(ticker: str, start: str = "1970-01-01") -> pd.DataFrame:
    """Daily OHLCV from the Nasdaq public API (raw prices, ~10y depth)."""
    fromdate = pd.Timestamp(start).strftime("%Y-%m-%d")
    last_err: Exception | None = None
    for assetclass in ("etf", "stocks"):
        url = (f"https://api.nasdaq.com/api/quote/{ticker}/historical"
               f"?assetclass={assetclass}&fromdate={fromdate}&limit=99999")
        try:
            payload = _get_json(url, {"Accept": "application/json"},
                                allow_empty=True)
            if not payload.get("data"):
                continue  # wrong asset class for this symbol; try the next
            rows = payload["data"]["tradesTable"]["rows"]

            def _f(x: str) -> float:
                try:
                    return float(str(x).replace(",", "").replace("$", ""))
                except (TypeError, ValueError):
                    return np.nan  # Nasdaq emits 'N/A' for halted/partial rows

            df = pd.DataFrame({
                "date": pd.to_datetime([r["date"] for r in rows]),
                "open": [_f(r["open"]) for r in rows],
                "high": [_f(r["high"]) for r in rows],
                "low": [_f(r["low"]) for r in rows],
                "close": [_f(r["close"]) for r in rows],
                "volume": [_f(r["volume"]) for r in rows],
            }).set_index("date").sort_index().dropna(subset=["close"])
            if len(df) > 50:
                return df
        except Exception as e:  # try the other asset class
            last_err = e
    raise RuntimeError(f"Nasdaq download failed for {ticker}: {last_err}")


# ---------------------------------------------------------------- cleaning

def clean_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Sort, dedupe, coerce, sanity-check. Returns (clean_df, checks)."""
    df = df.copy()
    df.index = pd.to_datetime(df.index).normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    before = len(df)
    df = df.dropna(subset=["close"])
    eps = 1e-9
    viol = int(((df["low"] > df[["open", "close"]].min(axis=1) + eps) |
                (df["high"] < df[["open", "close"]].max(axis=1) - eps)).sum())
    if "adj_close" in df and df["adj_close"].notna().any():
        df["adj_factor"] = df["adj_close"] / df["close"]
    checks = {"rows_in": before, "rows_out": len(df), "ohlc_violations": viol}
    return df, checks


def cross_check(ticker: str, yahoo: pd.DataFrame, nasdaq: pd.DataFrame) -> dict:
    """Raw-close agreement between the two sources on their overlap."""
    both = pd.DataFrame({"yahoo": yahoo["close"], "nasdaq": nasdaq["close"]}).dropna()
    if len(both) < 50:
        return {"overlap_days": len(both)}
    rel = (both["yahoo"] / both["nasdaq"] - 1).abs()
    return {"overlap_days": len(both),
            "mean_abs_diff_pct": float(rel.mean() * 100),
            "max_abs_diff_pct": float(rel.max() * 100),
            "days_over_0.5pct": int((rel > 0.005).sum())}


# ---------------------------------------------------------------- storage

def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _save_manifest(entry: dict) -> None:
    manifest = {}
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest[entry["ticker"]] = entry
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                        encoding="utf-8")


def build_dataset(ticker: str, start: str = "1970-01-01",
                  source: str = "yahoo", refresh: bool = False) -> dict:
    """Fetch (or incrementally update) one ticker into data_store/.

    Incremental rule: if a clean file exists and refresh is False, only
    the last 10 days are re-fetched and merged (dedupe keeps the new
    rows), so daily updates are cheap and corrections propagate.
    """
    for d in (RAW, CLEAN, EVENTS):
        d.mkdir(parents=True, exist_ok=True)
    clean_path = CLEAN / f"{ticker}.parquet"
    fetch_from = start
    existing = None
    if clean_path.exists() and not refresh:
        existing = pd.read_parquet(clean_path)
        fetch_from = (existing.index[-1] - pd.Timedelta(days=10)) \
            .strftime("%Y-%m-%d")

    if source == "yahoo":
        raw, events = fetch_yahoo(ticker, start=fetch_from)
    else:
        raw, events = fetch_nasdaq(ticker, start=fetch_from), \
            pd.DataFrame(columns=["date", "type", "value"])
    raw.to_csv(RAW / f"{ticker}_{source}.csv")
    if len(events):
        ev_path = EVENTS / f"{ticker}_events.csv"
        if ev_path.exists() and existing is not None:
            # Incremental fetches only see recent events; merge with the
            # stored history instead of overwriting it.
            old = pd.read_csv(ev_path, parse_dates=["date"])
            events = pd.concat([old, events]) \
                .drop_duplicates(subset=["date", "type"], keep="last") \
                .sort_values("date").reset_index(drop=True)
        events.to_csv(ev_path, index=False)

    clean, checks = clean_frame(raw)
    if existing is not None:
        clean = clean_frame(pd.concat([existing, clean]))[0]
    clean.to_parquet(clean_path)

    entry = {"ticker": ticker, "source": source,
             "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "rows": len(clean),
             "start": str(clean.index[0].date()),
             "end": str(clean.index[-1].date()),
             "clean_file": str(clean_path.relative_to(ROOT)),
             "sha256_16": _sha256(clean_path), **checks}
    _save_manifest(entry)
    return entry


def load_clean(ticker: str) -> pd.DataFrame:
    """Read one cleaned dataset (OHLCV + adj_close) from data_store/."""
    return pd.read_parquet(CLEAN / f"{ticker}.parquet")


def load_adj_close(tickers: list[str]) -> pd.DataFrame:
    """Wide adj_close matrix (total-return prices) for the strategy layer.

    This is the series strategies should consume: it reinvests dividends
    and neutralises splits, unlike the old split-only close.
    """
    return pd.DataFrame({t: load_clean(t)["adj_close"] for t in tickers})


# ---------------------------------------------------------------- audit

def audit(tickers: list[str]) -> pd.DataFrame:
    """One-row-per-ticker quality report over data_store/clean."""
    frames = {t: load_clean(t) for t in tickers}
    calendar = sorted(set().union(*[set(f.index) for f in frames.values()]))
    rows = []
    for t, f in frames.items():
        adj = f["adj_close"].dropna() if "adj_close" in f else f["close"]
        jumps = adj.pct_change()
        ev_path = EVENTS / f"{t}_events.csv"
        n_div = n_split = 0
        if ev_path.exists():
            ev = pd.read_csv(ev_path)
            n_div = int((ev["type"] == "dividend").sum())
            n_split = int((ev["type"] == "split").sum())
        in_range = [d for d in calendar if f.index[0] <= d <= f.index[-1]]
        rows.append({
            "ticker": t, "rows": len(f),
            "start": str(f.index[0].date()), "end": str(f.index[-1].date()),
            "missing_vs_union_calendar": len(set(in_range) - set(f.index)),
            "max_adj_jump_pct": round(float(jumps.abs().max()) * 100, 2),
            "n_dividends": n_div, "n_splits": n_split,
            "total_return_raw_%": round(float(f["close"].iloc[-1] / f["close"].iloc[0] - 1) * 100, 1),
            "total_return_adj_%": round(float(adj.iloc[-1] / adj.iloc[0] - 1) * 100, 1),
        })
    return pd.DataFrame(rows)
