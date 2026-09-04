"""腾讯日线 OHLCV(前复权),``web.ifzq.gtimg.cn/appstock/app/fqkline/get``。

默认配置里放 ``core_stock_apis`` 链尾,是 AmazingData(本地银河/QMT)与 Tushare 之后的
第三个**真正独立**的上游 —— 前两档都不是腾讯系,任一家挂掉这一档还能出数。

⚠️ 上游行序是 ``[日期, 开, 收, 高, 低, 量]`` —— **收盘价在第 3 位**,不是常见的 OHLC
顺序。按 OHLC 读会静默产出错误的最高/最低价,这类错误不会报错只会污染指标。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

from .akshare_utils import display_symbol, is_a_share, to_bare_code, to_prefixed_code
from .errors import NoMarketDataError
from .tencent_utils import fetch_text

_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

# 上游一次最多给多少根 K 线。请求窗口按自然日算,交易日约为其 70%,留足余量。
_MAX_BARS = 640

# qfqday 每行的下标(实测)
_ROW_DATE, _ROW_OPEN, _ROW_CLOSE, _ROW_HIGH, _ROW_LOW, _ROW_VOLUME = 0, 1, 2, 3, 4, 5


def _extract_bars(payload: str, prefixed: str) -> list[list[str]]:
    """从响应里取出 K 线数组。前复权时键是 ``qfqday``,未复权时是 ``day``。"""
    data = (json.loads(payload).get("data") or {}).get(prefixed) or {}
    bars = data.get("qfqday") or data.get("day") or []
    return [row for row in bars if isinstance(row, list) and len(row) > _ROW_VOLUME]


def get_stock_data(
    symbol: Annotated[str, "Mainland China ticker (600519, 600519.SS, 510300, ...)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """返回前复权日线 OHLCV 的 CSV 字符串,形状与 ``tushare_stock.get_stock_data`` 一致。"""
    if not is_a_share(symbol):
        raise NoMarketDataError(symbol, symbol, "not a mainland symbol for Tencent")

    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")

    code = to_bare_code(symbol)
    label = display_symbol(symbol)
    prefixed = to_prefixed_code(symbol).lower()

    payload = fetch_text(
        _KLINE_URL,
        params={"param": f"{prefixed},day,{start_date},{end_date},{_MAX_BARS},qfq"},
    )
    bars = _extract_bars(payload, prefixed)

    rows = []
    for bar in bars:
        date = str(bar[_ROW_DATE])[:10]
        # 上游对区间边界并不严格,自己再过滤一遍:回测绝不能看到 end_date 之后的价格。
        if not (start_date <= date <= end_date):
            continue
        rows.append(
            f"{date},{bar[_ROW_OPEN]},{bar[_ROW_HIGH]},{bar[_ROW_LOW]},"
            f"{bar[_ROW_CLOSE]},{bar[_ROW_VOLUME]}"
        )

    if not rows:
        raise NoMarketDataError(
            symbol, code, f"Tencent returned no daily bars between {start_date} and {end_date}"
        )

    header = (
        f"## {label} daily OHLCV (Tencent, forward-adjusted), "
        f"from {start_date} to {end_date}:\n\n"
    )
    return header + "Date,Open,High,Low,Close,Volume\n" + "\n".join(rows) + "\n"
