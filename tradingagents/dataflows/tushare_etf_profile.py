"""Tushare-backed ETF profile fallback.

This intentionally reuses the existing Tushare fund fundamentals report rather
than inventing a second Tushare shape. It gives the router ETF basics, T+1
OHLCV/NAV/adjustment data, and quarterly holdings. Note the T+1 shape: there is
no real-time IOPV / discount-premium here, and no vendor supplies one since
AKShare was removed from routing.
"""

from __future__ import annotations

from .errors import NoMarketDataError
from .tushare_fundamentals import get_fundamentals
from .tushare_utils import is_fund_symbol


def get_etf_profile(symbol: str, curr_date: str | None = None) -> str:
    if not is_fund_symbol(symbol):
        raise NoMarketDataError(symbol, symbol, "not a mainland China listed ETF/fund")
    return get_fundamentals(symbol, curr_date)
