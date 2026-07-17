"""AmazingData 沪深/ETF 技术指标(经 stockstats 本地计算)。

与 ``akshare_indicator`` 完全同构:同一 stockstats 计算、同一 5 年回看窗口 +
look-ahead 过滤、同一输出字符串格式,只有 OHLCV 数据源换成 AmazingData(前复权)。
指标目录文案与描述**直接复用** ``akshare_indicator``,使各市场的 agent 提示词读起来
完全一致。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import pandas as pd
from dateutil.relativedelta import relativedelta
from stockstats import wrap

from .akshare_indicator import _SUPPORTED, _indicator_description
from .amazingdata_stock import _adjust_for, _fetch_kline, _normalize_frame
from .amazingdata_utils import is_mainland_symbol, to_ad_code
from .errors import NoMarketDataError


def _load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """加载 5 年前复权 OHLCV(截至 curr_date,look-ahead 过滤)。

    与 ``stockstats_utils.load_ohlcv`` 语义一致:固定 5 年窗口以满足 200 周期均线的
    历史需求,再丢弃 curr_date 之后的行以防回测前视偏差。返回带 ``Date`` 列(非索引)
    的 frame,因为下方 stockstats ``wrap`` 与逐日循环期望这种形状。
    """
    ad_code = to_ad_code(symbol)
    curr_dt = pd.to_datetime(curr_date)
    start = (curr_dt - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    end = curr_dt.strftime("%Y-%m-%d")

    raw = _fetch_kline(ad_code, start, end, adjust=_adjust_for(symbol))
    if raw is None or raw.empty:
        raise NoMarketDataError(symbol, symbol, "AmazingData returned no rows for indicators")

    data = _normalize_frame(raw).reset_index()
    data = data[data["Date"] <= curr_dt]
    if data.empty:
        raise NoMarketDataError(symbol, symbol, "no rows on/before curr_date")
    return data


def _bulk_indicator(symbol: str, indicator: str, curr_date: str) -> dict:
    """Compute ``indicator`` for every available date; return {date_str: value}."""
    data = _load_ohlcv(symbol, curr_date)
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
    """Return per-day indicator values over the look-back window for a mainland instrument.

    Same signature and output format as the AKShare/Yahoo indicator paths so the
    router can swap vendors transparently.
    """
    if not is_mainland_symbol(symbol):
        raise NoMarketDataError(symbol, symbol, "not a mainland symbol for AmazingData")
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

    description = _indicator_description(indicator)

    return (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {end_date}:\n\n"
        + ind_string
        + "\n\n"
        + description
    )
