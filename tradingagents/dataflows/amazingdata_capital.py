"""AmazingData(银河证券)资金面/事件面数据:龙虎榜、融资融券、股东户数、业绩预告。

这些是 Tushare 免费档拿不到、可补齐的**新增分析维度**。经常驻服务 ``/call``
反射端点调用 InfoData 的对应方法(带 ``local_path="/cache"``、``is_local=True``
的本地缓存方案)。统一整形:look-ahead 过滤公告/交易日、按日期降序、精选字段映射
中文标签输出 CSV;空数据抛 ``NoMarketDataError``,由路由转成 NO_DATA 兜底句。
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from .amazingdata_stock import _extract_records
from .amazingdata_utils import (
    cached_call,
    call_amazingdata,
    display_symbol,
    to_ad_code,
)
from .errors import NoMarketDataError

_CAPITAL_TTL_SECONDS = 12 * 3600

_DRAGON_TIGER_FIELDS = [
    ("交易日", "TRADE_DATE"),
    ("名称", "SECURITY_NAME"),
    ("上榜原因", "REASON_TYPE_NAME"),
    ("涨跌幅%", "CHANGE_RANGE"),
    ("营业部", "TRADER_NAME"),
    ("买入额", "BUY_AMOUNT"),
    ("卖出额", "SELL_AMOUNT"),
    ("买卖(1买2卖)", "FLOW_MARK"),
    ("成交额", "TOTAL_AMOUNT"),
]
_MARGIN_FIELDS = [
    ("交易日", "TRADE_DATE"),
    ("融资余额", "BORROW_MONEY_BALANCE"),
    ("融资买入额", "PURCH_WITH_BORROW_MONEY"),
    ("融资偿还额", "REPAYMENT_OF_BORROW_MONEY"),
    ("融券余额", "SEC_LENDING_BALANCE"),
    ("融资融券余额", "MARGIN_TRADE_BALANCE"),
]
_HOLDER_FIELDS = [
    ("公告日", "ANN_DT"),
    ("统计截止日", "HOLDER_ENDDATE"),
    ("A股股东户数", "HOLDER_NUM"),
    ("总户数", "HOLDER_TOTAL_NUM"),
]
_PROFIT_NOTICE_FIELDS = [
    ("公告日", "ANN_DATE"),
    ("报告期", "REPORTING_PERIOD"),
    ("报告期名称", "REPORT_TYPE"),
    ("预告净利下限(万)", "NET_PROFIT_MIN"),
    ("预告净利上限(万)", "NET_PROFIT_MAX"),
    ("净利变动下限%", "P_CHANGE_MIN"),
    ("净利变动上限%", "P_CHANGE_MAX"),
    ("上年同期归母", "P_NET_PARENT_FIRM"),
    ("变动原因", "P_REASON"),
    ("摘要", "P_SUMMARY"),
]

_DATE_COLUMNS = {"TRADE_DATE", "ANN_DT", "ANN_DATE", "HOLDER_ENDDATE", "REPORTING_PERIOD", "FIRST_ANN_DATE"}


def _call_info(method: str, ad_code: str) -> list:
    cache_key = f"call/info/{method}/{ad_code}"

    def _fetch():
        return call_amazingdata(
            "/call",
            method="POST",
            json={
                "target": "info",
                "method": method,
                "args": [[ad_code]],
                "kwargs": {"local_path": "/cache", "is_local": True},
            },
            timeout=120.0,
        )

    resp = cached_call(cache_key, _CAPITAL_TTL_SECONDS, _fetch)
    return _extract_records(resp, ad_code)


def _project(df: pd.DataFrame, field_specs: list) -> pd.DataFrame:
    out = {}
    for label, field in field_specs:
        if field not in df.columns:
            continue
        series = df[field]
        if field in _DATE_COLUMNS:
            series = pd.to_datetime(
                series.astype(str), format="%Y%m%d", errors="coerce"
            ).dt.strftime("%Y-%m-%d")
        out[label] = series.values
    return pd.DataFrame(out)


def _capital_report(
    symbol: str,
    method: str,
    date_field: str,
    field_specs: list,
    title: str,
    curr_date: str | None,
    limit: int,
) -> str:
    label = display_symbol(symbol)
    ad_code = to_ad_code(symbol)
    records = _call_info(method, ad_code)
    if not records:
        raise NoMarketDataError(symbol, label, f"no AmazingData {title} records")

    df = pd.DataFrame(records)
    if date_field not in df.columns:
        raise NoMarketDataError(symbol, label, f"unexpected {title} schema")

    df = df.copy()
    df["_d"] = pd.to_datetime(df[date_field].astype(str), format="%Y%m%d", errors="coerce")
    if curr_date:
        df = df[df["_d"] <= pd.Timestamp(curr_date)]
    if df.empty:
        raise NoMarketDataError(symbol, label, f"no {title} on/before {curr_date}")

    df = df.sort_values("_d", ascending=False).head(limit)
    out = _project(df, field_specs)
    if out.empty:
        raise NoMarketDataError(symbol, label, f"no core {title} fields")

    header = f"# {title} for {label} (AmazingData / 银河证券)\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + out.to_csv(index=False)


def get_dragon_tiger(ticker: str, curr_date: str | None = None) -> str:
    """龙虎榜(近期上榜明细:上榜原因、营业部买卖额)。"""
    return _capital_report(
        ticker, "get_long_hu_bang", "TRADE_DATE", _DRAGON_TIGER_FIELDS,
        "Dragon-Tiger List (龙虎榜)", curr_date, limit=30,
    )


def get_margin_trading(ticker: str, curr_date: str | None = None) -> str:
    """融资融券个股明细(近 20 个交易日的融资/融券余额与买入偿还)。"""
    return _capital_report(
        ticker, "get_margin_detail", "TRADE_DATE", _MARGIN_FIELDS,
        "Margin Trading (融资融券)", curr_date, limit=20,
    )


def get_shareholders(ticker: str, curr_date: str | None = None) -> str:
    """股东户数(近期各报告期的 A 股股东户数变化)。"""
    return _capital_report(
        ticker, "get_holder_num", "ANN_DT", _HOLDER_FIELDS,
        "Shareholder Count (股东户数)", curr_date, limit=12,
    )


def get_profit_forecast(ticker: str, curr_date: str | None = None) -> str:
    """业绩预告(近期预告净利润区间、变动幅度与原因)。"""
    return _capital_report(
        ticker, "get_profit_notice", "ANN_DATE", _PROFIT_NOTICE_FIELDS,
        "Profit Forecast (业绩预告)", curr_date, limit=8,
    )
