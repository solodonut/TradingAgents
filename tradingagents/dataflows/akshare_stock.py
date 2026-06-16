"""AKShare A-share OHLCV price data.

Mirrors the public contract of ``y_finance.get_YFin_data_online``: same
arguments, same CSV-with-header return string, and the same typed
``NoMarketDataError`` on empty/stale data so the routing layer treats AKShare
exactly like any other vendor.

AKShare returns Chinese column names from East Money; we rename them to the
canonical ``Open/High/Low/Close/Volume`` set so downstream stockstats/indicator
code (which is column-name sensitive) works unchanged.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import akshare as ak
import pandas as pd

from .akshare_utils import (
    ak_retry,
    cached_call,
    display_symbol,
    is_a_share,
    is_etf_code,
    to_bare_code,
)
from .errors import NoMarketDataError
from .stockstats_utils import MAX_OHLCV_STALE_DAYS

# Daily OHLCV is cached for 6 hours: long enough to make repeated same-session
# runs instant, short enough that a same-day re-run picks up the latest close.
_PRICE_TTL_SECONDS = 6 * 3600

# East Money / AKShare Chinese column -> canonical English OHLCV column.
_COLUMN_MAP = {
    "日期": "Date",
    "开盘": "Open",
    "收盘": "Close",
    "最高": "High",
    "最低": "Low",
    "成交量": "Volume",
    "成交额": "Amount",
}


def _fetch_hist(code: str, start: str, end: str, adjust: str = "qfq") -> pd.DataFrame:
    """Fetch daily OHLCV for a bare 6-digit code, retried, proxy-bypassed, cached.

    ``adjust='qfq'`` (前复权 / forward-adjusted) is the standard choice for
    technical analysis: it keeps the latest price equal to the real quote and
    adjusts history for splits/dividends, which is what indicators expect.
    Dates are passed to AKShare in YYYYMMDD form.
    """
    start_compact = start.replace("-", "")
    end_compact = end.replace("-", "")
    cache_key = f"hist_{code}_{adjust}_{start_compact}_{end_compact}"

    endpoint = ak.fund_etf_hist_em if is_etf_code(code) else ak.stock_zh_a_hist

    def _fetch():
        return ak_retry(lambda: endpoint(
            symbol=code,
            period="daily",
            start_date=start_compact,
            end_date=end_compact,
            adjust=adjust,
        ))

    return cached_call(cache_key, _PRICE_TTL_SECONDS, _fetch)


def _normalize_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Rename Chinese columns to canonical OHLCV and index by date.

    Produces a frame whose index is the (tz-naive) date and whose columns
    include Open/High/Low/Close/Volume, matching the shape yfinance hands the
    formatter so the resulting CSV looks identical to the US path.
    """
    df = raw.rename(columns=_COLUMN_MAP).copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date")
    keep = [c for c in ("Open", "High", "Low", "Close", "Volume", "Amount") if c in df.columns]
    df = df[keep]
    for col in ("Open", "High", "Low", "Close", "Amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(2)
    if "Volume" in df.columns:
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    return df


def get_stock_data(
    symbol: Annotated[str, "A-share ticker (600519, 600519.SS, sh600519, ...)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Return A-share daily OHLCV as a CSV string with a descriptive header.

    Same return contract as ``y_finance.get_YFin_data_online``. Raises
    ``NoMarketDataError`` (routed into the standard NO_DATA sentinel) when the
    symbol is not an A-share, returns no rows, or returns only stale rows.
    """
    if not is_a_share(symbol):
        # Defensive: the router should only send A-shares here, but never
        # fabricate data for a symbol AKShare cannot serve.
        raise NoMarketDataError(symbol, symbol, "not an A-share symbol for AKShare")

    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")
    code = to_bare_code(symbol)
    label = display_symbol(symbol)

    raw = _fetch_hist(code, start_date, end_date)
    if raw is None or raw.empty:
        raise NoMarketDataError(
            symbol, label, f"no rows between {start_date} and {end_date}"
        )

    data = _normalize_frame(raw)
    if data.empty:
        raise NoMarketDataError(
            symbol, label, f"no usable rows between {start_date} and {end_date}"
        )

    # Stale-data guard, mirroring the Yahoo path: refuse a frame whose latest
    # row is far older than the requested end_date rather than feeding old
    # prices to the agent.
    latest = data.index.max().normalize()
    requested = pd.to_datetime(end_date).normalize()
    stale_days = (requested - latest).days
    if stale_days > MAX_OHLCV_STALE_DAYS:
        raise NoMarketDataError(
            symbol,
            label,
            f"latest row is {latest.date()}, {stale_days} days before the "
            f"requested {requested.date()} (stale) — refusing to use it",
        )

    csv_string = data.to_csv()
    header = f"# Stock data for {label} (A-share, AKShare) from {start_date} to {end_date}\n"
    header += f"# Total records: {len(data)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + csv_string
