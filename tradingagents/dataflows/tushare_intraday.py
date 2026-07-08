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


_FUND_TTL_SECONDS = 24 * 3600


def _fetch_fund_basic_row(ts_code: str) -> dict:
    def _fetch():
        df = call_tushare(lambda: get_tushare_client().fund_basic(ts_code=ts_code))
        return df.iloc[0].to_dict() if df is not None and not df.empty else {}

    return cached_call(f"fund_basic_kv/{ts_code}", _FUND_TTL_SECONDS, _fetch)


def _fetch_fund_nav_row(ts_code: str, trade_date: str) -> dict:
    end = trade_date.replace("-", "")

    def _fetch():
        df = call_tushare(
            lambda: get_tushare_client().fund_nav(ts_code=ts_code, end_date=end)
        )
        return df.iloc[0].to_dict() if df is not None and not df.empty else {}

    return cached_call(f"fund_nav_kv/{ts_code}/{end}", _FUND_TTL_SECONDS, _fetch)


def get_etf_fundamentals_kv(symbol: str, trade_date: str) -> dict:
    ts_code = to_ts_code(symbol)
    basic = _fetch_fund_basic_row(ts_code) or {}
    nav = _fetch_fund_nav_row(ts_code, trade_date) or {}

    candidates = [
        ("基金简称", basic.get("name")),
        ("上市日期", basic.get("list_date")),
        ("管理人", basic.get("management")),
        ("最新净值", nav.get("unit_nav") or nav.get("accum_nav")),
        ("份额(万)", nav.get("fund_share")),
    ]
    items = [
        {"label": label, "value": str(value)}
        for label, value in candidates
        if value not in (None, "", "nan")
    ]
    if not items:
        raise NoMarketDataError(symbol, ts_code, "no fundamentals fields")
    return {"items": items}
