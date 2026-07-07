import logging
import time

import requests

from tradingagents.obs.run_logger import get_current_run_logger

from .akshare_fundamentals import (
    get_akshare_etf_profile,
    get_balance_sheet as get_akshare_balance_sheet,
    get_cashflow as get_akshare_cashflow,
    get_fundamentals as get_akshare_fundamentals,
    get_income_statement as get_akshare_income_statement,
)
from .akshare_indicator import get_indicators as get_akshare_indicators
from .akshare_news import get_news as get_akshare_news
from .akshare_stock import get_stock_data as get_akshare_stock
from .akshare_utils import is_a_share as _is_a_share_symbol
from .alpha_vantage import (
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_global_news as get_alpha_vantage_global_news,
    get_income_statement as get_alpha_vantage_income_statement,
    get_indicator as get_alpha_vantage_indicator,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_stock as get_alpha_vantage_stock,
)
from .config import get_config
from .eastmoney_news import get_news as get_eastmoney_news
from .errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)
from .fred import get_macro_data as get_fred_macro_data
from .longbridge import (
    get_etf_profile as get_longbridge_etf_profile,
    get_news as get_longbridge_news,
)
from .polymarket import get_prediction_markets as get_polymarket_prediction_markets
from .tdx import get_etf_profile as get_tdx_etf_profile
from .tushare_etf_profile import get_etf_profile as get_tushare_etf_profile
from .tushare_fundamentals import (
    get_balance_sheet as get_tushare_balance_sheet,
    get_cashflow as get_tushare_cashflow,
    get_fundamentals as get_tushare_fundamentals,
    get_income_statement as get_tushare_income_statement,
)
from .tushare_indicator import get_indicators as get_tushare_indicators
from .tushare_news import get_global_news as get_tushare_global_news, get_news as get_tushare_news
from .tushare_stock import get_stock_data as get_tushare_stock
from .y_finance import (
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_fundamentals as get_yfinance_fundamentals,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
    get_stock_stats_indicators_window,
    get_YFin_data_online,
)
from .yfinance_news import get_global_news_yfinance, get_news_yfinance

logger = logging.getLogger(__name__)

DISABLED_VENDOR_SENTINELS = {"disabled", "none", "off"}

# Transient connectivity failures (host unreachable, proxy refuses to tunnel,
# timeout, chunked-read abort). When the configured vendor chain fails ONLY
# with these — and no vendor reports clean "no data" — route_to_vendor returns
# an UNAVAILABLE sentinel instead of re-raising, so one unreachable data source
# degrades to "data unavailable" for that single tool call rather than crashing
# the whole multi-agent run. Honors the "never raises" contract in AGENTS.md.
# requests wraps the underlying urllib3 RemoteDisconnected in ConnectionError.
_NETWORK_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.ProxyError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    },
    "macro_data": {
        "description": "Macroeconomic indicators (rates, inflation, labor, growth)",
        "tools": [
            "get_macro_indicators",
        ]
    },
    "prediction_markets": {
        "description": "Market-implied probabilities for forward-looking events",
        "tools": [
            "get_prediction_markets",
        ]
    },
    "etf_data": {
        "description": "ETF-specific data: discount/premium, IOPV, scale, holdings",
        "tools": [
            "get_etf_profile",
        ]
    }
}

VENDOR_LIST = [
    "yfinance",
    "fred",
    "polymarket",
    "alpha_vantage",
    "tushare",
    "akshare",
    "eastmoney",
    "longbridge",
    "tdx",
]


def _tushare_not_ready(*args, **kwargs):
    raise VendorNotConfiguredError("Tushare vendor is not implemented/configured yet.")


# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
        "tushare": get_tushare_stock,
        "akshare": get_akshare_stock,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        "tushare": get_tushare_indicators,
        "akshare": get_akshare_indicators,
    },
    # fundamental_data
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
        "tushare": get_tushare_fundamentals,
        "akshare": get_akshare_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
        "tushare": get_tushare_balance_sheet,
        "akshare": get_akshare_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
        "tushare": get_tushare_cashflow,
        "akshare": get_akshare_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
        "tushare": get_tushare_income_statement,
        "akshare": get_akshare_income_statement,
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
        "longbridge": get_longbridge_news,
        "akshare": get_akshare_news,
        "eastmoney": get_eastmoney_news,
        "tushare": get_tushare_news,
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
        "tushare": get_tushare_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
    # macro_data
    "get_macro_indicators": {
        "fred": get_fred_macro_data,
    },
    # prediction_markets
    "get_prediction_markets": {
        "polymarket": get_polymarket_prediction_markets,
    },
    # etf_data
    "get_etf_profile": {
        "akshare": get_akshare_etf_profile,
        "tushare": get_tushare_etf_profile,
        "tdx": get_tdx_etf_profile,
        "longbridge": get_longbridge_etf_profile,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    all_available_vendors = list(VENDOR_METHODS[method].keys())

    # The configured vendor list IS the chain: we do NOT silently fall back to
    # vendors the user did not choose (#988/#289) — that returned data from an
    # unexpected source and caused cross-vendor inconsistencies. For multi-vendor
    # fallback, list them in order, e.g. data_vendors="yfinance,alpha_vantage".
    # The "default" sentinel (no explicit config) uses all available vendors.
    if any(v.lower() in DISABLED_VENDOR_SENTINELS for v in primary_vendors if v):
        return (
            f"DATA_SOURCE_DISABLED: Data source for '{method}' is disabled by "
            f"configuration for category '{category}'. Do not estimate or fabricate "
            "values — report that this data source is unavailable in the current "
            "domestic China-only setup."
        )

    explicit = [v for v in primary_vendors if v and v != "default"]
    if explicit:
        vendor_chain = [v for v in explicit if v in VENDOR_METHODS[method]]
        if not vendor_chain:
            raise ValueError(
                f"Configured vendor(s) {explicit} not available for '{method}'. "
                f"Available: {all_available_vendors}."
            )
    else:
        vendor_chain = all_available_vendors

    # A-share auto-routing: when the requested symbol is a mainland A-share
    # (600519, 600519.SS, sh600519, ...) and AKShare implements this method,
    # try AKShare first for legacy Yahoo/Alpha Vantage chains. Explicit chains
    # that include Tushare keep their configured order, so the production
    # default "tushare,akshare" tries Tushare first and falls back to AKShare
    # while the Tushare implementation is still a placeholder. Disable with
    # config ``akshare_auto_route = False``.
    config = get_config()
    explicit_vendor_names = {v.lower() for v in explicit}
    if (
        config.get("akshare_auto_route", True)
        and "akshare" in VENDOR_METHODS[method]
        and "tushare" not in explicit_vendor_names
        and "longbridge" not in explicit_vendor_names
        and "tdx" not in explicit_vendor_names
    ):
        symbol = args[0] if args else kwargs.get("symbol") or kwargs.get("ticker")
        if isinstance(symbol, str) and _is_a_share_symbol(symbol):
            vendor_chain = ["akshare"] + [v for v in vendor_chain if v != "akshare"]

    _run_logger = get_current_run_logger()
    _t0 = time.time()

    def _emit_vendor(vendor, ok, **extra):
        if _run_logger is None:
            return
        _run_logger.emit(
            "vendor_call",
            method=method,
            vendor=vendor,
            ok=ok,
            args=_run_logger.truncate(str(args)),
            elapsed_ms=(time.time() - _t0) * 1000,
            **extra,
        )

    last_no_data: NoMarketDataError | None = None
    first_error: Exception | None = None
    network_error: Exception | None = None
    for vendor in vendor_chain:
        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            result = impl_func(*args, **kwargs)
            if (
                method == "get_news"
                and isinstance(result, str)
                and result.startswith("Error fetching news")
            ):
                logger.warning(
                    "Vendor %r returned a news error sentinel for %s; trying next vendor.",
                    vendor,
                    method,
                )
                if first_error is None:
                    first_error = NoMarketDataError(
                        str(args[0]) if args else str(kwargs.get("ticker", "")),
                        detail=result,
                    )
                _emit_vendor(vendor, False, error="news_error_sentinel")
                continue
            _emit_vendor(vendor, True, fallback=(vendor != vendor_chain[0]))
            return result
        except VendorRateLimitError:
            logger.warning("Vendor %r rate-limited for %s; trying next vendor.", vendor, method)
            _emit_vendor(vendor, False, error="rate_limited")
            continue
        except VendorNotConfiguredError as e:
            logger.warning("Vendor %r not configured for %s; trying next vendor.", vendor, method)
            if first_error is None:
                first_error = e  # Surface it if no other vendor can serve the call.
            _emit_vendor(vendor, False, error="not_configured")
            continue
        except NoMarketDataError as e:
            last_no_data = e  # No data here; another configured vendor may have it
            _emit_vendor(vendor, False, error="no_data")
            continue
        except Exception as e:
            # Don't let one vendor's failure crash the call when another can
            # serve it, but never swallow silently: a broken primary must be
            # visible in the logs (#989), not hidden behind a fallback's verdict.
            logger.warning("Vendor %r failed for %s: %s", vendor, method, e)
            if isinstance(e, _NETWORK_ERRORS) and network_error is None:
                network_error = e
            if first_error is None:
                first_error = e
            _emit_vendor(vendor, False, error=str(e))
            continue

    # If any vendor reported "no data", the symbol is genuinely unavailable.
    # Return one explicit, instructive sentinel rather than a vendor-specific
    # empty string, so the agent reports "unavailable" instead of inventing a
    # value. This takes precedence over incidental fallback errors.
    if last_no_data is not None:
        if first_error is not None:
            # A vendor also hit a real error; surface it in logs so the no-data
            # verdict can't hide a broken primary (network/auth/etc.).
            logger.warning(
                "Returning NO_DATA for %s, but a vendor errored earlier: %s",
                method, first_error,
            )
        sym = last_no_data.symbol
        canonical = last_no_data.canonical
        resolved = "" if canonical == sym else f" (resolved to '{canonical}')"
        # Surface the typed error's detail (e.g. "latest row is 2025-06-11 ...
        # stale") so the agent sees the specific reason — invalid symbol, no
        # coverage, or stale data — not just a generic "unavailable".
        reason = f" ({last_no_data.detail})" if last_no_data.detail else ""
        _emit_vendor(None, False, no_data=True)
        return (
            f"NO_DATA_AVAILABLE: No usable market data for '{sym}'{resolved} from "
            f"any configured vendor{reason}. The symbol may be invalid, delisted, "
            f"not covered, or the vendor returned stale data. Do not estimate or "
            f"fabricate values — report that data is unavailable for this symbol."
        )

    # No vendor returned data and none reported clean "no data". If the only
    # failures were transient connectivity errors (upstream host unreachable or
    # blocked, e.g. East Money refusing non-mainland egress), do NOT crash the
    # run: return an explicit UNAVAILABLE sentinel so the agent reports the
    # source as down instead of aborting the whole analysis (honors the
    # "never raises" contract). Genuine non-network errors (bad symbol, parse
    # bug) still raise — those are programming/data errors that must surface.
    # Use the network error from ANY vendor in the chain, not just the first
    # failure: when an unconfigured primary (e.g. Tushare without a token) fails
    # before a secondary hits a transient outage, the network error lands second
    # and must still win — otherwise the misleading "not configured" error gets
    # raised and crashes the run instead of degrading gracefully.
    if network_error is not None:
        logger.warning(
            "A vendor for %s failed with a network error; returning "
            "DATA_SOURCE_UNAVAILABLE sentinel instead of raising: %s",
            method, network_error,
        )
        return (
            f"DATA_SOURCE_UNAVAILABLE: Could not reach any data source for "
            f"'{method}' due to a network/connectivity error ({network_error}). "
            f"The data vendor host may be unreachable or blocked from this "
            f"network. Do not estimate or fabricate values — report that this "
            f"data is temporarily unavailable."
        )

    # A non-network error from the primary vendor — surface it loudly.
    if first_error is not None:
        raise first_error

    raise RuntimeError(f"No available vendor for '{method}'")
