"""AKShare vendor helpers: symbol resolution, A-share detection, proxy handling.

AKShare scrapes Chinese public market sources (East Money, Sina, etc.) that are
hosted in mainland China. Two facts shape this module:

1. A-share tickers come in several user-facing forms that all refer to the same
   instrument. We normalize them to the two shapes AKShare endpoints expect:

       user types        meaning                 akshare wants
       ---------------   ---------------------   ----------------------------
       600519            bare 6-digit code       "600519"        (hist)
       600519.SS         Yahoo Shanghai suffix   "600519" + "SH" prefix
       000001.SZ         Yahoo Shenzhen suffix   "000001" + "SZ" prefix
       sh600519 / SH..   broker prefix form      stripped / re-derived

   The exchange is derived deterministically from the numeric code when no
   suffix is given, using the standard Shanghai/Shenzhen/Beijing code ranges.

2. The host environment may export corporate HTTP(S) proxies that cannot reach
   mainland endpoints (the proxy closes the connection). ``no_proxy_session``
   temporarily clears every proxy env var the requests stack reads so AKShare's
   internal ``requests.get`` calls go direct. Restored on exit so the rest of
   the process (LLM API calls through the corporate proxy) is unaffected.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import time

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Proxy env vars the requests/urllib3 stack consults, lower- and upper-case.
_PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)

# Transient network failures from East Money / Sina worth retrying. urllib3
# wraps the underlying RemoteDisconnected in these requests-level types.
_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.ProxyError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

# A bare A-share code is exactly six digits. Suffix forms append a market tag.
_BARE_CODE = re.compile(r"^\d{6}$")
# Yahoo-style suffixes for the two mainland exchanges (case-insensitive).
_YAHOO_SUFFIX = re.compile(r"^(\d{6})\.(SS|SZ)$", re.IGNORECASE)
# Broker prefix form: sh600519 / sz000001 / bj430047.
_PREFIX_FORM = re.compile(r"^(SH|SZ|BJ)(\d{6})$", re.IGNORECASE)


@contextlib.contextmanager
def no_proxy_session():
    """Force AKShare's HTTP calls to bypass every proxy and reach mainland hosts.

    The corporate proxy (when present) cannot tunnel to East Money / Sina, so
    AKShare requests must go direct. Clearing the proxy env vars is NOT enough:
    on macOS, ``requests`` reads the system proxy via the OS configuration
    layer, which env-var clearing does not affect. The only reliable switch is
    ``Session.trust_env = False``, so we monkeypatch the ``Session.__init__``
    default for the duration. AKShare creates its sessions inside this block,
    so they all inherit the bypass. Env vars are also cleared (belt and braces)
    and everything is restored on exit so LLM provider calls — which DO need
    the corporate proxy — keep working.
    """
    saved = {k: os.environ.pop(k, None) for k in _PROXY_ENV_KEYS}
    prior_no_proxy = os.environ.get("NO_PROXY")
    prior_no_proxy_lc = os.environ.get("no_proxy")
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

    original_init = requests.Session.__init__

    def _no_trust_env_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.trust_env = False

    requests.Session.__init__ = _no_trust_env_init
    try:
        yield
    finally:
        requests.Session.__init__ = original_init
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
        if prior_no_proxy is None:
            os.environ.pop("NO_PROXY", None)
        else:
            os.environ["NO_PROXY"] = prior_no_proxy
        if prior_no_proxy_lc is None:
            os.environ.pop("no_proxy", None)
        else:
            os.environ["no_proxy"] = prior_no_proxy_lc


def ak_retry(func, max_retries: int = 6, base_delay: float = 1.0):
    """Run an AKShare call with proxy bypass and exponential backoff.

    East Money intermittently drops connections (``RemoteDisconnected``), often
    several times in a row, so a small retry budget is unreliable. This wraps
    the call in ``no_proxy_session`` and retries transient network errors with
    capped exponential backoff. Non-network exceptions (bad symbol, parse
    errors) propagate immediately — retrying them would only waste time.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with no_proxy_session():
                return func()
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), 8.0)
                logger.warning(
                    "AKShare network error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, max_retries, delay, exc,
                )
                time.sleep(delay)
            else:
                logger.warning("AKShare exhausted %d retries: %s", max_retries, exc)
    raise last_exc


def _cache_dir() -> str:
    """Return the AKShare cache directory, honoring the project's cache config."""
    from .config import get_config

    base = get_config().get("data_cache_dir") or os.path.join(
        os.path.expanduser("~"), ".tradingagents", "cache"
    )
    path = os.path.join(base, "akshare")
    os.makedirs(path, exist_ok=True)
    return path


def cached_call(key: str, ttl_seconds: int, func):
    """Return a cached DataFrame for ``key`` or fetch, cache, and return it.

    Statement endpoints are slow (East Money paginates ~20 requests, ~1 min),
    so we persist results to a parquet/pickle file keyed by ``key`` and reuse
    them until ``ttl_seconds`` elapses. A cache miss (absent, expired, or
    unreadable) calls ``func`` and rewrites the cache. ``func`` is responsible
    for its own proxy handling (use ``ak_retry``); ``cached_call`` only adds the
    on-disk layer. Returns whatever ``func`` returns when caching is impossible,
    so a write failure never blocks the data path.
    """
    safe_key = re.sub(r"[^A-Za-z0-9_.\-]", "_", key)
    cache_file = os.path.join(_cache_dir(), f"{safe_key}.pkl")

    if os.path.exists(cache_file):
        age = time.time() - os.path.getmtime(cache_file)
        if age < ttl_seconds:
            try:
                return pd.read_pickle(cache_file)
            except Exception as exc:
                logger.warning("AKShare cache unreadable (%s), refetching: %s", cache_file, exc)

    result = func()
    with contextlib.suppress(Exception):
        if isinstance(result, pd.DataFrame):
            result.to_pickle(cache_file)
    return result


def _exchange_for_code(code: str) -> str:
    """Return 'SH', 'SZ', or 'BJ' for a bare 6-digit A-share code.

    Standard mainland code ranges:
      Shanghai  (SH): 60xxxx (main board), 68xxxx (STAR/科创板),
                      9xxxxx (B-shares), 5xxxxx (funds)
      Shenzhen  (SZ): 00xxxx (main board), 30xxxx (ChiNext/创业板),
                      200xxx (B-shares), 1/15/16/18xxxx (funds)
      Beijing   (BJ): 43xxxx, 83xxxx, 87xxxx, 88xxxx, 920xxx (北交所)
    Shanghai is the conservative default for anything unrecognized.
    """
    if code.startswith(("60", "68", "90", "50", "51", "52", "56", "58")):
        return "SH"
    if code.startswith(("00", "30", "20", "15", "16", "18", "12", "13")):
        return "SZ"
    if code.startswith(("43", "83", "87", "88", "92")):
        return "BJ"
    return "SH"


def is_etf_code(code: str) -> bool:
    """True when a bare 6-digit code is a fund/ETF rather than a common stock.

    Fund/ETF code ranges: Shenzhen 15/16/18, Shanghai 50/51/52/56/58. These
    are served by East Money's ``fund_etf_hist_em`` endpoint, NOT the
    ``stock_zh_a_hist`` endpoint that common stocks (60/68 SH, 00/30 SZ) use.
    """
    return code.startswith(("15", "16", "18", "50", "51", "52", "56", "58"))


def is_a_share(symbol: str) -> bool:
    """True when ``symbol`` denotes a mainland A-share in any accepted form.

    Accepts bare 6-digit codes (600519), Yahoo suffix forms (600519.SS,
    000001.SZ), and broker prefix forms (sh600519). Pure US-style tickers
    (AAPL), Hong Kong (.HK), and other markets return False so the router keeps
    sending them to Yahoo.
    """
    if not isinstance(symbol, str):
        return False
    s = symbol.strip()
    if not s:
        return False
    return bool(
        _BARE_CODE.match(s)
        or _YAHOO_SUFFIX.match(s)
        or _PREFIX_FORM.match(s)
    )


def to_bare_code(symbol: str) -> str:
    """Return the bare 6-digit code from any accepted A-share form.

    600519 -> 600519 · 600519.SS -> 600519 · sh600519 -> 600519.
    Raises ValueError if ``symbol`` is not a recognizable A-share symbol.
    """
    s = symbol.strip()
    if _BARE_CODE.match(s):
        return s
    m = _YAHOO_SUFFIX.match(s)
    if m:
        return m.group(1)
    m = _PREFIX_FORM.match(s)
    if m:
        return m.group(2)
    raise ValueError(f"{symbol!r} is not a recognizable A-share symbol")


def to_prefixed_code(symbol: str) -> str:
    """Return the SH/SZ/BJ-prefixed code AKShare financial endpoints expect.

    600519 -> SH600519 · 000001.SZ -> SZ000001 · sh600519 -> SH600519.
    The exchange is taken from the suffix/prefix when present, otherwise
    derived from the numeric code range. Raises ValueError on non-A-share input.
    """
    s = symbol.strip()
    m = _YAHOO_SUFFIX.match(s)
    if m:
        code, suffix = m.group(1), m.group(2).upper()
        exch = "SH" if suffix == "SS" else "SZ"
        return f"{exch}{code}"
    m = _PREFIX_FORM.match(s)
    if m:
        return f"{m.group(1).upper()}{m.group(2)}"
    if _BARE_CODE.match(s):
        return f"{_exchange_for_code(s)}{s}"
    raise ValueError(f"{symbol!r} is not a recognizable A-share symbol")


def display_symbol(symbol: str) -> str:
    """Canonical display label for an A-share: bare code + exchange suffix.

    600519 -> 600519.SS · 000001.SZ -> 000001.SZ. Used in report headers so
    the agent always sees an unambiguous, Yahoo-compatible identifier.
    """
    code = to_bare_code(symbol)
    exch = _exchange_for_code(code)
    suffix = {"SH": "SS", "SZ": "SZ", "BJ": "BJ"}[exch]
    return f"{code}.{suffix}"
