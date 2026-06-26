from __future__ import annotations

import contextlib
import os
import re
import time

import pandas as pd
import requests

from .akshare_utils import display_symbol, is_a_share, is_etf_code, to_bare_code
from .errors import VendorError, VendorNotConfiguredError, VendorRateLimitError

try:
    import tushare as ts
except ModuleNotFoundError as exc:
    if exc.name != "tushare":
        raise

    class _MissingTushare:
        def set_token(self, token: str):
            raise TushareNotConfiguredError("The tushare package is not installed.")

        def pro_api(self):
            raise TushareNotConfiguredError("The tushare package is not installed.")

    ts = _MissingTushare()

_CLIENT = None


class TushareNotConfiguredError(VendorNotConfiguredError):
    """Tushare was selected but no usable token/configuration is available."""


class TushareRateLimitError(VendorRateLimitError):
    """Tushare rejected a request for quota, points, permission, or throttling."""


def reset_tushare_client():
    """Clear the cached Tushare Pro client, primarily for tests."""
    global _CLIENT
    _CLIENT = None


def get_tushare_client():
    """Return a cached Tushare Pro client configured from ``TUSHARE_TOKEN``."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise TushareNotConfiguredError("TUSHARE_TOKEN is not configured.")

    ts.set_token(token)
    _CLIENT = ts.pro_api()
    return _CLIENT


_TOKEN_PATTERNS = (
    "token",
    "tushare_token",
    "无效token",
    "token无效",
    "token为空",
    "token不存在",
)
_RATE_LIMIT_PATTERNS = (
    "权限",
    "积分",
    "积分不足",
    "访问次数",
    "访问频次",
    "每分钟",
    "每小时",
    "每秒",
    "频率",
    "限制",
    "permission",
    "points",
    "rate limit",
    "too many requests",
    "quota",
)


def call_tushare(func):
    """Run a Tushare call and normalize common vendor messages to typed errors."""
    try:
        return func()
    except VendorError:
        raise
    except requests.exceptions.RequestException:
        raise
    except Exception as exc:
        message = str(exc)
        normalized = message.lower()
        if any(pattern in normalized for pattern in _TOKEN_PATTERNS):
            raise TushareNotConfiguredError(message) from exc
        if any(pattern in normalized for pattern in _RATE_LIMIT_PATTERNS):
            raise TushareRateLimitError(message) from exc
        raise


def _cache_dir() -> str:
    from .config import get_config

    base = get_config().get("data_cache_dir") or os.path.join(
        os.path.expanduser("~"), ".tradingagents", "cache"
    )
    path = os.path.join(base, "tushare")
    os.makedirs(path, exist_ok=True)
    return path


def cached_call(key: str, ttl_seconds: int, func):
    """Cache pandas DataFrame results for a Tushare call without including tokens."""
    safe_key = re.sub(r"[^A-Za-z0-9_.\-]", "_", key)
    cache_file = os.path.join(_cache_dir(), f"{safe_key}.pkl")

    if os.path.exists(cache_file):
        age = time.time() - os.path.getmtime(cache_file)
        if age < ttl_seconds:
            try:
                return pd.read_pickle(cache_file)
            except Exception:
                pass

    result = func()
    with contextlib.suppress(Exception):
        if isinstance(result, pd.DataFrame):
            result.to_pickle(cache_file)
    return result


def to_ts_code(symbol: str) -> str:
    """Return a Tushare ``ts_code`` such as ``600519.SH`` or ``000001.SZ``."""
    s = symbol.strip()
    m = re.match(r"^(\d{6})\.(SS|SH|SZ|BJ)$", s, re.IGNORECASE)
    if m:
        code, suffix = m.group(1), m.group(2).upper()
        if suffix == "SS":
            suffix = "SH"
        return f"{code}.{suffix}"

    canonical = display_symbol(symbol)
    if canonical.endswith(".SS"):
        return f"{to_bare_code(canonical)}.SH"
    return canonical


def is_mainland_symbol(symbol: str) -> bool:
    """True when ``symbol`` denotes a mainland China market instrument."""
    return is_a_share(symbol)


def is_fund_symbol(symbol: str) -> bool:
    """True when ``symbol`` is a recognized mainland fund/ETF code."""
    try:
        return is_etf_code(to_bare_code(symbol))
    except ValueError:
        return False
