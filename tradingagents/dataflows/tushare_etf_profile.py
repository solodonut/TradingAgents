"""Tushare-backed ETF profile fallback.

This intentionally reuses the existing Tushare fund fundamentals report rather
than inventing a second Tushare shape. It gives the router a stable fallback for
ETF basics, T+1 OHLCV/NAV/adjustment data, and quarterly holdings when AKShare's
real-time ETF snapshot is unreachable.
"""

from __future__ import annotations

from .errors import NoMarketDataError
from .tushare_fundamentals import get_fundamentals
from .tushare_utils import is_fund_symbol


def get_etf_profile(symbol: str, curr_date: str | None = None) -> str:
    if not is_fund_symbol(symbol):
        raise NoMarketDataError(symbol, symbol, "not a mainland China listed ETF/fund")
    return get_fundamentals(symbol, curr_date)
