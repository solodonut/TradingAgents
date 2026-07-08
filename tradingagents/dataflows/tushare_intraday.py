"""Tushare Pro intraday minute bars for mainland ETFs (stk_mins covers ETF codes)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from .errors import NoMarketDataError
from .tushare_utils import (
    cached_call,
    call_tushare,
    display_symbol,
    get_tushare_client,
    is_fund_symbol,
    to_ts_code,
)

_INTRADAY_TTL_SECONDS = 6 * 3600
_DAILY_TTL_SECONDS = 6 * 3600


def _fetch_mins(ts_code: str, trade_date: str, freq: str) -> pd.DataFrame:
    start = f"{trade_date} 09:00:00"
    end = f"{trade_date} 15:30:00"
    cache_key = f"stk_mins/{ts_code}/{trade_date}/{freq}"

    def _fetch():
        client = get_tushare_client()
        return call_tushare(
            lambda: client.stk_mins(
                ts_code=ts_code, freq=freq, start_date=start, end_date=end
            )
        )

    return cached_call(cache_key, _INTRADAY_TTL_SECONDS, _fetch)


def get_etf_intraday(symbol: str, trade_date: str, freq: str = "5min") -> dict:
    ts_code = to_ts_code(symbol)
    raw = _fetch_mins(ts_code, trade_date, freq)
    if raw is None or raw.empty or "trade_time" not in raw.columns:
        raise NoMarketDataError(symbol, ts_code, "no intraday minute data")

    df = raw.sort_values("trade_time")
    points = [
        {
            "t": str(row["trade_time"])[11:16],
            "price": float(row["close"]),
            "vol": float(row.get("vol", 0) or 0),
        }
        for _, row in df.iterrows()
    ]
    if not points:
        raise NoMarketDataError(symbol, display_symbol(symbol), "empty intraday points")
    return {"trade_date": trade_date, "freq": freq, "points": points}


def _fetch_daily_raw(ts_code: str, start: str, end: str) -> pd.DataFrame:
    endpoint_name = "fund_daily" if is_fund_symbol(ts_code) else "daily"
    cache_key = f"kline/{endpoint_name}/{ts_code}/{start}/{end}"

    def _fetch():
        endpoint = getattr(get_tushare_client(), endpoint_name)
        return call_tushare(lambda: endpoint(ts_code=ts_code, start_date=start, end_date=end))

    return cached_call(cache_key, _DAILY_TTL_SECONDS, _fetch)


def get_etf_daily_kline(symbol: str, trade_date: str, lookback: int = 60) -> dict:
    ts_code = to_ts_code(symbol)
    end = trade_date.replace("-", "")
    start_dt = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=lookback * 2 + 10)
    start = start_dt.strftime("%Y%m%d")
    raw = _fetch_daily_raw(ts_code, start, end)
    if raw is None or raw.empty or "trade_date" not in raw.columns:
        raise NoMarketDataError(symbol, ts_code, "no daily kline data")

    df = raw.sort_values("trade_date").tail(lookback)
    kline = [
        {
            "date": f"{str(r['trade_date'])[:4]}-{str(r['trade_date'])[4:6]}-{str(r['trade_date'])[6:8]}",
            "o": float(r["open"]),
            "h": float(r["high"]),
            "l": float(r["low"]),
            "c": float(r["close"]),
            "vol": float(r.get("vol", 0) or 0),
        }
        for _, r in df.iterrows()
    ]
    if not kline:
        raise NoMarketDataError(symbol, ts_code, "empty daily kline")
    return {"kline": kline}
