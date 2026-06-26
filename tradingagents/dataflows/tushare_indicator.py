"""Tushare Pro technical indicators computed locally with stockstats.

Tushare adds no new indicator semantics: it loads Tushare OHLCV, normalizes it
into the same shape used by AKShare/yfinance, then computes indicators locally
with ``stockstats``. The supported catalog and output string format are reused
verbatim from the AKShare path so agent prompts read identically across vendors.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import pandas as pd
from dateutil.relativedelta import relativedelta
from stockstats import wrap

from .akshare_indicator import _indicator_description
from .errors import NoMarketDataError
from .tushare_stock import _fetch_daily, _normalize_frame
from .tushare_utils import is_mainland_symbol, to_ts_code

_SUPPORTED = (
    "close_50_sma", "close_200_sma", "close_10_ema",
    "macd", "macds", "macdh",
    "rsi", "boll", "boll_ub", "boll_lb", "atr", "vwma", "mfi",
)


def _load_tushare_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Load 5y of Tushare OHLCV up to curr_date, look-ahead filtered.

    Mirrors ``akshare_indicator._load_akshare_ohlcv``: a fixed 5-year window so
    200-period averages have enough history, then rows after curr_date are
    dropped to prevent look-ahead bias. Returned with a ``Date`` column (not
    index) because ``stockstats.wrap`` and the window loop expect that shape.
    """
    ts_code = to_ts_code(symbol)
    curr_dt = pd.to_datetime(curr_date)
    start = (curr_dt - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    end = curr_dt.strftime("%Y-%m-%d")

    raw = _fetch_daily(ts_code, start, end)
    if raw is None or raw.empty:
        raise NoMarketDataError(symbol, symbol, "Tushare returned no rows for indicators")

    data = _normalize_frame(raw).reset_index()
    if data.empty:
        raise NoMarketDataError(symbol, symbol, "no usable Tushare rows for indicators")
    data = data[data["Date"] <= curr_dt]
    if data.empty:
        raise NoMarketDataError(symbol, symbol, "no Tushare rows on/before curr_date")
    return data


def _bulk_indicator(symbol: str, indicator: str, curr_date: str) -> dict:
    """Compute ``indicator`` for every available date; return {date_str: value}."""
    data = _load_tushare_ohlcv(symbol, curr_date)
    df = wrap(data)
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    df[indicator]  # trigger stockstats calculation
    result = {}
    for _, row in df.iterrows():
        value = row[indicator]
        result[row["Date"]] = "N/A" if pd.isna(value) else str(value)
    return result


def get_indicators(
    symbol: Annotated[str, "Mainland ticker (600519, 600519.SS, 159241, ...)"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """Return per-day indicator values over the look-back window for a mainland symbol.

    Same signature and output format as the AKShare/yfinance paths so the router
    can swap vendors transparently.
    """
    if not is_mainland_symbol(symbol):
        raise NoMarketDataError(symbol, symbol, "not a mainland China symbol for Tushare")
    if indicator not in _SUPPORTED:
        raise ValueError(
            f"Indicator {indicator} is not supported. Please choose from: {list(_SUPPORTED)}"
        )

    end_date = curr_date
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_dt - relativedelta(days=look_back_days)

    indicator_data = _bulk_indicator(symbol, indicator, curr_date)

    cursor = curr_dt
    ind_string = ""
    while cursor >= before:
        date_str = cursor.strftime("%Y-%m-%d")
        value = indicator_data.get(date_str, "N/A: Not a trading day (weekend or holiday)")
        ind_string += f"{date_str}: {value}\n"
        cursor = cursor - relativedelta(days=1)

    return (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {end_date}:\n\n"
        + ind_string
        + "\n\n"
        + _indicator_description(indicator)
    )
