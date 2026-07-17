"""AmazingData(银河证券)沪深/ETF 日线 OHLCV(前复权)。

经常驻服务 ``/kline`` 端点取数(``adjust="qfq"``)。首次 qfq 调用需取后复权因子
(实测约 38s),因此在记录级缓存(``cached_call``,6h TTL)。字段整形为与 Tushare
路径同构的 CSV,使路由可透明切换 vendor。``_fetch_kline``/``_normalize_frame``
抽出供指标模块复用。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import pandas as pd

from .amazingdata_utils import (
    cached_call,
    call_amazingdata,
    display_symbol,
    is_fund_symbol,
    is_mainland_symbol,
    to_ad_code,
)
from .errors import NoMarketDataError
from .stockstats_utils import MAX_OHLCV_STALE_DAYS

_PRICE_TTL_SECONDS = 6 * 3600

_COLUMN_MAP = {
    "kline_time": "Date",
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume": "Volume",
    "amount": "Amount",
}


def _extract_records(resp: dict, ad_code: str) -> list:
    """从服务响应取出记录列表。

    ``data`` 形态因端点而异:``/kline``、``/financial`` 及部分 ``/call`` 方法返回
    ``{code: [records]}``(dict);另一些 ``/call`` 方法(SDK 返回单个 DataFrame)
    直接序列化为 ``[records]``(list)。两种都兼容。
    """
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        records = data.get(ad_code)
        if records is None and len(data) == 1:
            records = next(iter(data.values()))
        return records or []
    return []


def _fetch_kline(
    ad_code: str, start_date: str, end_date: str, adjust: str = "qfq"
) -> pd.DataFrame:
    """拉取日线原始记录并转 DataFrame(记录级缓存)。"""
    start_int = int(start_date.replace("-", ""))
    end_int = int(end_date.replace("-", ""))
    cache_key = f"kline/{ad_code}/{start_int}/{end_int}/day/{adjust}"

    def _fetch():
        return call_amazingdata(
            "/kline",
            method="POST",
            json={
                "code_list": [ad_code],
                "begin_date": start_int,
                "end_date": end_int,
                "period": "day",
                "adjust": adjust,
            },
            timeout=180.0,
        )

    resp = cached_call(cache_key, _PRICE_TTL_SECONDS, _fetch)
    return pd.DataFrame(_extract_records(resp, ad_code))


def _adjust_for(symbol: str) -> str:
    """股票用前复权(指标跨除权需要);ETF 无需复权且因子拉取极慢,用不复权。"""
    return "none" if is_fund_symbol(symbol) else "qfq"


def _normalize_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """重命名为 Date 索引 + Open/High/Low/Close/Volume/Amount,数值化并排序。"""
    if raw is None or raw.empty:
        return pd.DataFrame()
    df = raw.rename(columns=_COLUMN_MAP).copy()
    value_columns = ["Open", "High", "Low", "Close", "Volume", "Amount"]
    required = ["Date", *value_columns]
    if any(col not in df.columns for col in required):
        return pd.DataFrame()

    # 日线 kline_time 为整型 YYYYMMDD(如 20260710)。
    df["Date"] = pd.to_datetime(df["Date"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["Date"]).set_index("Date")
    df = df[value_columns]

    for col in value_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=value_columns)
    return df.sort_index()


def get_stock_data(
    symbol: Annotated[str, "Mainland China ticker (600519, 600519.SS, 159241, ...)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Return mainland daily OHLCV (前复权) as a CSV string with a descriptive header."""
    if not is_mainland_symbol(symbol):
        raise NoMarketDataError(symbol, symbol, "not a mainland symbol for AmazingData")

    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")
    label = display_symbol(symbol)
    ad_code = to_ad_code(symbol)
    adjust = _adjust_for(symbol)

    raw = _fetch_kline(ad_code, start_date, end_date, adjust=adjust)
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

    adjust_label = "前复权" if adjust == "qfq" else "不复权"
    header = (
        f"# Stock data for {label} (AmazingData / 银河证券, {adjust_label}) "
        f"from {start_date} to {end_date}\n"
    )
    header += f"# Total records: {len(data)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + data.to_csv()
