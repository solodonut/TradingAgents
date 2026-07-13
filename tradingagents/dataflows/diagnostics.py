"""Read-only diagnostic probes over the VENDOR_METHODS data-source matrix.

Intentionally bypasses ``route_to_vendor`` (which only tries configured vendors
and stops at first success) to test EVERY (method, vendor) cell individually.
This is a deliberate, approved exception to the AGENTS.md rule that all data
access goes through ``route_to_vendor``. Read-only: no checkpoint, no run lock,
no config mutation. Honors the "never raises" contract — ``probe_cell`` catches
everything and reports a status instead of propagating.
"""

from __future__ import annotations

from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)
from tradingagents.dataflows.interface import _NETWORK_ERRORS

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
