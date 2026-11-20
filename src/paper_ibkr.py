"""IBKR paper-trading execution layer (paper accounts ONLY).

Safety design — this module is built so it *cannot* place a live order:

1. Port lock: only IBKR paper ports are accepted
   (7497 = TWS paper, 4002 = IB Gateway paper).
   Live ports (7496 / 4001) and anything else raise immediately.
2. Account lock: after connecting, every managed account must be a
   paper account (IBKR paper account ids start with "DU"). A live
   account id ("U...") aborts the run before any order is built.
3. Dry-run first: order placement only happens when the caller
   explicitly passes execute=True (the CLI defaults to dry-run).

Sizing note: the IBKR API does not support fractional shares (fractional
orders are manual-platform only), so quantities are whole shares.
With a small budget sleeve this matters: qty = floor(budget / price),
which is 0 when one share costs more than the whole sleeve.

The pure helpers (assert_paper_endpoint, latest_signal, whole_share_qty,
plan_order) have no IBKR dependency and are unit-testable offline.
The ib_async import is lazy, inside connect_ibkr().
"""
from __future__ import annotations

import math

import pandas as pd

PAPER_PORTS = {7497, 4002}   # TWS paper, IB Gateway paper
LIVE_PORTS = {7496, 4001}    # TWS live, IB Gateway live


class PaperSafetyError(RuntimeError):
    """Raised when a connection or order might touch a live account."""


def assert_paper_endpoint(port: int, account: str | None = None) -> None:
    """Refuse anything that is not unambiguously a paper endpoint."""
    if port in LIVE_PORTS:
        raise PaperSafetyError(
            f"Port {port} is a LIVE IBKR port. This tool only runs on paper "
            f"ports {sorted(PAPER_PORTS)} (7497=TWS paper, 4002=Gateway paper)."
        )
    if port not in PAPER_PORTS:
        raise PaperSafetyError(
            f"Port {port} is not a known IBKR paper port {sorted(PAPER_PORTS)}."
        )
    if account is not None:
        assert_paper_account(account)


def assert_paper_account(account: str) -> None:
    """Refuse any account id that is not an IBKR paper (DU) account."""
    if not account.startswith("DU"):
        raise PaperSafetyError(
            f"Account {account!r} does not start with 'DU', so it is not an "
            "IBKR paper account. Aborting."
        )


def latest_signal(close: pd.Series, fast: int = 50, slow: int = 200) -> dict:
    """Latest dual-SMA state for one ticker, using data up to the last close.

    Mirrors src/strategies.sma_trend for a single asset: hold while
    fast SMA > slow SMA. The signal is computed on today's close, so in
    live use it is only actionable from the next session — same
    anti-lookahead convention as the backtest engine.
    """
    close = close.dropna()
    if len(close) < slow:
        raise ValueError(f"Need at least {slow} closes, got {len(close)}")
    sma_fast = close.rolling(fast).mean().iloc[-1]
    sma_slow = close.rolling(slow).mean().iloc[-1]
    return {
        "date": close.index[-1],
        "close": float(close.iloc[-1]),
        "sma_fast": float(sma_fast),
        "sma_slow": float(sma_slow),
        "hold": bool(sma_fast > sma_slow),
    }


def whole_share_qty(budget: float, price: float) -> int:
    """Whole shares affordable within `budget` (IBKR API = no fractions)."""
    if price <= 0:
        raise ValueError("price must be positive")
    return int(math.floor(budget / price)) if budget > 0 else 0


def plan_order(current_qty: int, target_qty: int) -> dict:
    """Diff current vs target position into a single order (or none)."""
    diff = target_qty - current_qty
    if diff > 0:
        return {"action": "BUY", "qty": diff}
    if diff < 0:
        return {"action": "SELL", "qty": -diff}
    return {"action": "NONE", "qty": 0}


# --- IBKR connection (lazy import; not needed for dry-run) ---

def connect_ibkr(host: str = "127.0.0.1", port: int = 4002, client_id: int = 11):
    """Connect to a running TWS / IB Gateway *paper* session and verify
    that every managed account is a paper (DU) account."""
    assert_paper_endpoint(port)
    try:
        from ib_async import IB
    except ImportError as e:
        raise RuntimeError(
            "ib_async is not installed. Run: pip install ib_async"
        ) from e
    ib = IB()
    ib.connect(host, port, clientId=client_id, timeout=10)
    accounts = ib.managedAccounts()
    if not accounts:
        ib.disconnect()
        raise PaperSafetyError("Gateway returned no managed accounts.")
    for acct in accounts:
        if not acct.startswith("DU"):
            ib.disconnect()
            raise PaperSafetyError(
                f"Managed account {acct!r} is not a paper (DU) account. "
                "Disconnected without placing any order."
            )
    return ib, accounts


def current_position(ib, symbol: str) -> int:
    """Current whole-share position in `symbol` on the paper account."""
    for pos in ib.positions():
        if pos.contract.symbol == symbol:
            return int(pos.position)
    return 0


def place_paper_order(ib, symbol: str, plan: dict, account: str) -> object:
    """Place one market order on the verified paper account.

    The connection was already port- and account-checked by
    connect_ibkr(); here we re-check the account id before ordering."""
    assert_paper_account(account)
    if plan["action"] == "NONE" or plan["qty"] <= 0:
        return None
    from ib_async import MarketOrder, Stock

    contract = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(contract)
    order = MarketOrder(plan["action"], plan["qty"], account=account)
    return ib.placeOrder(contract, order)
