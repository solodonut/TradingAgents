"""AmazingData(银河证券)常驻服务桥接层。

TradingAgents 经本地 HTTP 复用 QMT 项目跑起来的 AmazingData 常驻服务(独占单点
登录),不直连银河、不抢占登录态。本模块仿 ``tushare_utils.py``:提供探测降级的
调用入口、把服务端 HTTP 错误翻译成 vendor 错误分类、落盘缓存,以及代码规范化。

代码规范化直接复用 ``tushare_utils``——AmazingData 用 ``.SH/.SZ`` 与 Tushare 的
``to_ts_code`` 输出一致,无需重造。
"""

from __future__ import annotations

import contextlib
import json as _json
import os
import re
import time
import urllib.error

from . import ad_service_client
from .errors import VendorError, VendorNotConfiguredError, VendorRateLimitError
from .tushare_utils import (
    display_symbol,
    is_fund_symbol,
    is_mainland_symbol,
    resolve_symbol_type,
    to_ts_code,
)

# AmazingData 代码规范化与 Tushare 一致(.SS -> .SH),直接复用。
to_ad_code = to_ts_code

__all__ = [
    "AmazingdataNotConfiguredError",
    "AmazingdataRateLimitError",
    "call_amazingdata",
    "cached_call",
    "to_ad_code",
    "display_symbol",
    "is_fund_symbol",
    "is_mainland_symbol",
    "resolve_symbol_type",
]


class AmazingdataNotConfiguredError(VendorNotConfiguredError):
    """AmazingData 被选中,但常驻服务离线/未登录/凭证无效——vendor 不可用。"""


class AmazingdataRateLimitError(VendorRateLimitError):
    """AmazingData 服务端暂时性故障(SDK/重登失败),路由跳到下一个 vendor。"""


_HTTP_CODE = re.compile(r"^HTTP (\d+):")
# 后端(银河)连接类故障的消息关键词。服务端把这些多以 403(PermissionError)或
# 400 抛出,但它们是暂时性可恢复的(下次调用会触发服务内 _guarded 重登),因此当作
# 限流让路由回退,而非编程 bug。实测过 "HTTP 403: Connect failed"。
_CONN_KEYWORDS = (
    "connect", "timeout", "not logged", "login", "session",
    "broken", "closed", "refused", "reset", "unavailable",
)


def call_amazingdata(
    path: str,
    *,
    method: str = "GET",
    params: dict | None = None,
    json: dict | None = None,
    timeout: float = 60.0,
):
    """探测服务后调用端点;把服务端错误归一为 vendor 错误分类。

    - 服务离线/未登录 -> ``AmazingdataNotConfiguredError``(路由回退下一个 vendor)。
    - HTTP 401(token 无效/缺失)-> ``AmazingdataNotConfiguredError``。
    - HTTP 429/5xx(限流/SDK 重登失败等暂时性故障)-> ``AmazingdataRateLimitError``。
    - HTTP 403/400 且消息含连接类关键词(如 "Connect failed",后端暂时不可达)
      -> ``AmazingdataRateLimitError``,让路由回退,不 crash 整个多 agent run。
    - 其余 HTTP 403/400(方法名错误/不在白名单)是编程 bug,不吞,原样抛出。
    - 探测通过后服务掉线(连接错误)-> ``AmazingdataNotConfiguredError``。
    """
    if not ad_service_client.service_available():
        raise AmazingdataNotConfiguredError("AmazingData service is offline or not logged in.")

    try:
        return ad_service_client.call(
            path, method=method, params=params, json=json, timeout=timeout
        )
    except VendorError:
        raise
    except RuntimeError as exc:
        message = str(exc)
        m = _HTTP_CODE.match(message)
        code = int(m.group(1)) if m else None
        lowered = message.lower()
        if code == 401:
            raise AmazingdataNotConfiguredError(message) from exc
        if code == 429 or (code is not None and 500 <= code <= 599):
            raise AmazingdataRateLimitError(message) from exc
        if any(k in lowered for k in _CONN_KEYWORDS):
            raise AmazingdataRateLimitError(message) from exc
        raise
    except (urllib.error.URLError, ConnectionError, OSError) as exc:
        raise AmazingdataNotConfiguredError(str(exc)) from exc


def _cache_dir() -> str:
    from .config import get_config

    base = get_config().get("data_cache_dir") or os.path.join(
        os.path.expanduser("~"), ".tradingagents", "cache"
    )
    path = os.path.join(base, "amazingdata")
    os.makedirs(path, exist_ok=True)
    return path


def cached_call(key: str, ttl_seconds: int, func):
    """缓存 AmazingData 服务的 JSON 响应到磁盘(不含 token)。

    qfq K线首次取复权因子约 38s,K线/复权/财务都值得缓存。空响应(meta.rows==0)
    不落盘——避免一次暂时性空结果毒化后续所有 run(见 ``etf_static_profile`` 的教训)。
    """
    safe_key = re.sub(r"[^A-Za-z0-9_.\-]", "_", key)
    cache_file = os.path.join(_cache_dir(), f"{safe_key}.json")

    if os.path.exists(cache_file):
        age = time.time() - os.path.getmtime(cache_file)
        if age < ttl_seconds:
            try:
                with open(cache_file, encoding="utf-8") as fh:
                    return _json.load(fh)
            except Exception:
                pass

    result = func()
    if _has_rows(result):
        with contextlib.suppress(Exception), open(cache_file, "w", encoding="utf-8") as fh:
            _json.dump(result, fh)
    return result


def _has_rows(result) -> bool:
    """服务响应是否携带非空数据(用于决定是否落盘)。"""
    if not isinstance(result, dict):
        return bool(result)
    meta = result.get("meta")
    if isinstance(meta, dict) and "rows" in meta:
        return bool(meta.get("rows"))
    return bool(result.get("data"))
