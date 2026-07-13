"""Read-only diagnostic probes over the VENDOR_METHODS data-source matrix.

Intentionally bypasses ``route_to_vendor`` (which only tries configured vendors
and stops at first success) to test EVERY (method, vendor) cell individually.
This is a deliberate, approved exception to the AGENTS.md rule that all data
access goes through ``route_to_vendor``. Read-only: no checkpoint, no run lock,
no config mutation. Honors the "never raises" contract — ``probe_cell`` catches
everything and reports a status instead of propagating.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)
from tradingagents.dataflows.interface import _NETWORK_ERRORS, VENDOR_METHODS

# "无权限"启发式关键词(小写)。缺 key 通常抛 VendorNotConfiguredError(走异常路径);
# 积分/付费档问题往往由 vendor 以普通错误文本返回,只能靠关键词高亮。非权威判定——
# 原始返回全文始终保留供人工确认。集中在此一处维护。
PERMISSION_HINTS: tuple[str, ...] = (
    "积分不足",
    "权限不足",
    "没有权限",
    "抱歉,您没有",
    "请开通",
    "token 无效",
    "invalid token",
    "premium",
    "subscription",
    "api key",
    "apikey",
    "unauthorized",
    "forbidden",
    "401",
    "403",
)


def classify_result(*, value: object | None = None, exc: BaseException | None = None) -> str:
    """把一次探测的结果四分类:ok / no_data / no_perm / unavailable。

    异常类型优先;否则按返回字符串的哨兵前缀 / 关键词判定;非字符串返回视为 ok。
    """
    if exc is not None:
        if isinstance(exc, VendorNotConfiguredError):
            return "no_perm"
        if isinstance(exc, VendorRateLimitError):
            return "unavailable"
        if isinstance(exc, NoMarketDataError):
            return "no_data"
        if isinstance(exc, _NETWORK_ERRORS):
            return "unavailable"
        return "unavailable"

    if isinstance(value, str):
        if value.startswith("NO_DATA_AVAILABLE:"):
            return "no_data"
        if value.startswith(("DATA_SOURCE_UNAVAILABLE:", "DATA_SOURCE_DISABLED:")):
            return "unavailable"
        if value.startswith("Error fetching news"):
            return "no_data"
        low = value.lower()
        if any(hint in low for hint in PERMISSION_HINTS):
            return "no_perm"
        return "ok"

    return "ok"


_MAX_RAW = 8000
_LOOKBACK_DAYS = 30


def _start(ref_date: str) -> str:
    return (datetime.strptime(ref_date, "%Y-%m-%d") - timedelta(days=_LOOKBACK_DAYS)).strftime(
        "%Y-%m-%d"
    )


# 方法 → UI 分区(3 组)。同一 TOOLS_CATEGORIES 类别下方法可能分属不同 UI 组,故按方法映射。
METHOD_GROUP: dict[str, str] = {
    "get_stock_data": "ETF 核心",
    "get_indicators": "ETF 核心",
    "get_etf_profile": "ETF 核心",
    "get_etf_intraday": "ETF 核心",
    "get_etf_news": "ETF 核心",
    "get_news": "ETF 核心",
    "get_fundamentals": "股票基本面",
    "get_balance_sheet": "股票基本面",
    "get_cashflow": "股票基本面",
    "get_income_statement": "股票基本面",
    "get_insider_transactions": "股票基本面",
    "get_global_news": "参考·与 ETF 无关",
    "get_macro_indicators": "参考·与 ETF 无关",
    "get_prediction_markets": "参考·与 ETF 无关",
}

# 每个方法一句中文说明,展示在诊断页。key 必须与 METHOD_GROUP 一致(测试保证)。
METHOD_DESC: dict[str, str] = {
    "get_stock_data": "日线 OHLCV 历史行情",
    "get_indicators": "技术指标(如 close_50_sma)",
    "get_etf_profile": "ETF 基本档案(规模 / 费率 / 跟踪指数)",
    "get_etf_intraday": "ETF 分时行情(默认 5min)",
    "get_etf_news": "ETF 相关新闻",
    "get_news": "标的相关新闻",
    "get_fundamentals": "基本面概况",
    "get_balance_sheet": "资产负债表(年报)",
    "get_cashflow": "现金流量表(年报)",
    "get_income_statement": "利润表(年报)",
    "get_insider_transactions": "内部人交易",
    "get_global_news": "全球宏观新闻",
    "get_macro_indicators": "宏观经济指标(如 CPI)",
    "get_prediction_markets": "预测市场行情(Polymarket)",
}

# 各方法签名不一,把 (code, ref_date) 映射成每个方法的实参。参数与生产调用方保持一致格式
# (curr_date 用 YYYY-MM-DD)。非 symbol 方法(global_news/macro/prediction)用固定参数、不注入 code。
METHOD_PROBES: dict[str, Callable[[str, str], tuple]] = {
    "get_stock_data": lambda c, d: (c, _start(d), d),
    "get_indicators": lambda c, d: (c, "close_50_sma", d, _LOOKBACK_DAYS),
    "get_etf_profile": lambda c, d: (c, d),
    "get_etf_intraday": lambda c, d: (c, d, "5min"),
    "get_etf_news": lambda c, d: (c, _start(d), d),
    "get_news": lambda c, d: (c, _start(d), d),
    "get_fundamentals": lambda c, d: (c, d),
    "get_balance_sheet": lambda c, d: (c, "annual", d),
    "get_cashflow": lambda c, d: (c, "annual", d),
    "get_income_statement": lambda c, d: (c, "annual", d),
    "get_insider_transactions": lambda c, d: (c,),
    "get_global_news": lambda c, d: (d, 7, 20),
    "get_macro_indicators": lambda c, d: ("CPI", d, 90),
    "get_prediction_markets": lambda c, d: ("stock market", 10),
}


@dataclass
class CellResult:
    method: str
    vendor: str
    group: str
    status: str
    elapsed_ms: float
    raw: str
    error_type: str | None


def _truncate(text: str) -> str:
    return text if len(text) <= _MAX_RAW else text[:_MAX_RAW] + "… (truncated)"


def probe_cell(method: str, vendor: str, code: str, ref_date: str) -> CellResult:
    """直接调用 VENDOR_METHODS[method][vendor],返回四态结果。绝不外抛。"""
    impl = VENDOR_METHODS[method][vendor]
    func = impl[0] if isinstance(impl, list) else impl
    args = METHOD_PROBES[method](code, ref_date)

    t0 = time.time()
    value: object | None = None
    exc: BaseException | None = None
    try:
        value = func(*args)
    except Exception as e:  # noqa: BLE001 — 诊断层遵守 never-raises,把异常变成状态
        exc = e
    elapsed_ms = (time.time() - t0) * 1000

    status = classify_result(value=value, exc=exc)
    if exc is not None:
        raw = f"{type(exc).__name__}: {exc}"
        error_type = type(exc).__name__
    else:
        raw = value if isinstance(value, str) else repr(value)
        error_type = None

    return CellResult(
        method=method,
        vendor=vendor,
        group=METHOD_GROUP[method],
        status=status,
        elapsed_ms=elapsed_ms,
        raw=_truncate(raw),
        error_type=error_type,
    )


def iter_probes(
    code: str, ref_date: str, vendors: set[str] | None = None
) -> Iterator[CellResult]:
    """串行遍历 (method, vendor) 格子。vendors=None 跑全部;否则只跑选中的供应商。

    串行是刻意的:避免并发触发限流、便于逐格计时。
    """
    for method, method_vendors in VENDOR_METHODS.items():
        for vendor in method_vendors:
            if vendors is not None and vendor not in vendors:
                continue
            yield probe_cell(method, vendor, code, ref_date)


def count_probes(vendors: set[str] | None = None) -> int:
    if vendors is None:
        return sum(len(v) for v in VENDOR_METHODS.values())
    return sum(1 for vs in VENDOR_METHODS.values() for v in vs if v in vendors)


def build_meta() -> dict:
    """供前端渲染:全部供应商(去重排序)+ 每个方法的分区与说明。纯读、无网络。"""
    vendors = sorted({v for vs in VENDOR_METHODS.values() for v in vs})
    methods = [
        {"name": m, "group": METHOD_GROUP[m], "desc": METHOD_DESC[m]}
        for m in METHOD_GROUP
    ]
    return {"vendors": vendors, "methods": methods}
