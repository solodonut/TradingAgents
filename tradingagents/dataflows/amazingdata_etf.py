"""AmazingData(银河证券)ETF 分钟级日内行情。

经常驻服务 ``/kline`` 端点取分钟 K 线(period 如 ``min5``),整形为与
``tushare_intraday.get_etf_intraday`` 同构的 dict(``{trade_date, freq, points}``),
使路由可透明切换 vendor。分钟 ``kline_time`` 为 ISO 字符串(如
``2026-07-10T09:30:00``)。
"""

from __future__ import annotations

import pandas as pd

from .amazingdata_stock import _extract_records
from .amazingdata_utils import cached_call, call_amazingdata, to_ad_code
from .errors import NoMarketDataError

_INTRADAY_TTL_SECONDS = 6 * 3600


def _freq_to_period(freq: str) -> str:
    """把 "5min"/"15min" 之类转成 AmazingData 的 period 串 "min5"/"min15"。"""
    f = (freq or "").strip().lower()
    if f.endswith("min") and f[:-3].isdigit():
        return f"min{f[:-3]}"
    return f


def _fetch_mins(ad_code: str, trade_date: str, period: str) -> list:
    day_int = int(trade_date.replace("-", ""))
    cache_key = f"kline_min/{ad_code}/{day_int}/{period}"

    def _fetch():
        return call_amazingdata(
            "/kline",
            method="POST",
            json={
                "code_list": [ad_code],
                "begin_date": day_int,
                "end_date": day_int,
                "period": period,
                "adjust": "none",
            },
            timeout=120.0,
        )

    resp = cached_call(cache_key, _INTRADAY_TTL_SECONDS, _fetch)
    return _extract_records(resp, ad_code)


def get_etf_intraday(symbol: str, trade_date: str, freq: str = "5min") -> dict:
    ad_code = to_ad_code(symbol)
    period = _freq_to_period(freq)
    records = _fetch_mins(ad_code, trade_date, period)
    if not records:
        raise NoMarketDataError(symbol, ad_code, "no intraday minute data")

    df = pd.DataFrame(records)
    if "kline_time" not in df.columns or "close" not in df.columns:
        raise NoMarketDataError(symbol, ad_code, "unexpected intraday schema")

    df = df.sort_values("kline_time")
    points = [
        {
            "t": str(row["kline_time"])[11:16],
            "price": float(row["close"]),
            "vol": float(row.get("volume", 0) or 0),
        }
        for _, row in df.iterrows()
    ]
    if not points:
        raise NoMarketDataError(symbol, ad_code, "empty intraday points")
    return {"trade_date": trade_date, "freq": freq, "points": points}
