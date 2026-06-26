"""Tushare Pro mainland daily OHLCV price data."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import pandas as pd

from .errors import NoMarketDataError
from .stockstats_utils import MAX_OHLCV_STALE_DAYS
from .tushare_utils import (
    cached_call,
    call_tushare,
    display_symbol,
    get_tushare_client,
    is_fund_symbol,
    is_mainland_symbol,
    to_ts_code,
)

_PRICE_TTL_SECONDS = 6 * 3600

_COLUMN_MAP = {
    "trade_date": "Date",
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "vol": "Volume",
    "amount": "Amount",
}


def _fetch_daily(ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    start_compact = start_date.replace("-", "")
    end_compact = end_date.replace("-", "")
    endpoint_name = "fund_daily" if is_fund_symbol(ts_code) else "daily"
    cache_key = f"{endpoint_name}/{ts_code}/{start_compact}/{end_compact}"

    def _fetch():
        client = get_tushare_client()
        endpoint = getattr(client, endpoint_name)
        return call_tushare(
            lambda: endpoint(
                ts_code=ts_code,
                start_date=start_compact,
                end_date=end_compact,
            )
        )

    return cached_call(cache_key, _PRICE_TTL_SECONDS, _fetch)


def _normalize_frame(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.rename(columns=_COLUMN_MAP).copy()
    required = ["Date", "Open", "High", "Low", "Close", "Volume"]
    if any(col not in df.columns for col in required):
        return pd.DataFrame()

    df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date")
    keep = [c for c in ("Open", "High", "Low", "Close", "Volume", "Amount") if c in df.columns]
    df = df[keep]

    for col in keep:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=required[1:])
    return df.sort_index()


def get_stock_data(
    symbol: Annotated[str, "Mainland China ticker (600519, 600519.SS, 159241, ...)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Return mainland daily OHLCV as a CSV string with a descriptive header."""
    if not is_mainland_symbol(symbol):
        raise NoMarketDataError(symbol, symbol, "not a mainland symbol for Tushare")

    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")
    label = display_symbol(symbol)
    ts_code = to_ts_code(symbol)

    raw = _fetch_daily(ts_code, start_date, end_date)
    if raw is None or raw.empty:
        raise NoMarketDataError(
            symbol, label, f"no rows between {start_date} and {end_date}"
        )

    data = _normalize_frame(raw)
    if data.empty:
        raise NoMarketDataError(
            symbol, label, f"no usable rows between {start_date} and {end_date}"
        )

    latest = data.index.max().normalize()
    requested = pd.to_datetime(end_date).normalize()
    stale_days = (requested - latest).days
    if stale_days > MAX_OHLCV_STALE_DAYS:
        raise NoMarketDataError(
            symbol,
            label,
            f"latest row is {latest.date()}, {stale_days} days before the "
            f"requested {requested.date()} (stale) - refusing to use it",
        )

    header = f"# Stock data for {label} (Tushare Pro) from {start_date} to {end_date}\n"
    header += f"# Total records: {len(data)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + data.to_csv()
