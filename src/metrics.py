"""Performance metrics for an equity curve."""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def summarize(equity: pd.Series, name: str = "strategy") -> dict:
    rets = equity.pct_change().dropna()
    years = len(rets) / TRADING_DAYS
    total = equity.iloc[-1] / equity.iloc[0] - 1
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    vol = rets.std() * np.sqrt(TRADING_DAYS)
    sharpe = (rets.mean() * TRADING_DAYS) / vol if vol > 0 else np.nan
    drawdown = equity / equity.cummax() - 1
    return {
        "name": name,
        "total_return": total,
        "cagr": cagr,
        "annual_vol": vol,
        "sharpe": sharpe,
        "max_drawdown": drawdown.min(),
        "final_equity": equity.iloc[-1],
    }


def format_summary(rows: list[dict]) -> str:
    header = f"{'':<16}{'总收益':>10}{'年化':>9}{'年化波动':>10}{'夏普':>7}{'最大回撤':>10}"
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r['name']:<16}{r['total_return']:>9.1%}{r['cagr']:>9.1%}"
            f"{r['annual_vol']:>10.1%}{r['sharpe']:>7.2f}{r['max_drawdown']:>10.1%}"
        )
    return "\n".join(lines)
