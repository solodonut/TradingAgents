"""Pre-fetch four ETF data categories and persist per-date snapshots.

Runs once per ETF right before its analysis. Never raises: any category that
fails after retries is marked ``missing`` so analysis proceeds with an explicit
"unavailable" marker rather than fabricated values.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from dateutil.relativedelta import relativedelta

from .config import get_config
from .errors import NoMarketDataError
from .interface import route_to_vendor
from .tushare_intraday import (
    get_etf_daily_kline,
    get_etf_fundamentals_kv,
    get_etf_intraday,
)
from .tushare_utils import resolve_symbol_type

_CATEGORIES = ("news", "intraday", "indicators", "fundamentals")
_NODATA_PREFIXES = ("NO_DATA_AVAILABLE", "DATA_SOURCE_")
# 详情页「技术指标/日线」区块展示的核心指标集:趋势(均线)+动量(rsi)+MACD+布林。
_PREFETCH_INDICATORS = ("macd", "rsi", "close_50_sma", "boll")


@dataclass
class CategoryResult:
    category: str
    status: str  # ok | partial | missing
    payload: dict


@dataclass
class SnapshotSummary:
    ticker: str
    trade_date: str
    results: list[CategoryResult]

    def _by(self, category: str) -> CategoryResult | None:
        return next((r for r in self.results if r.category == category), None)

    def for_context(self) -> dict:
        """Compact block pushed into analyst context (news text + quote + missing)."""
        missing = [r.category for r in self.results if r.status == "missing"]
        news = self._by("news")
        intraday = self._by("intraday")
        quote = None
        if intraday and intraday.status != "missing":
            pts = intraday.payload.get("points") or []
            if pts:
                quote = {"last_price": pts[-1]["price"], "trade_date": self.trade_date}
        return {
            "ticker": self.ticker,
            "trade_date": self.trade_date,
            "news_text": (news.payload.get("text") if news and news.status != "missing" else None),
            "quote": quote,
            "missing": missing,
        }


def _is_nodata(result) -> bool:
    return isinstance(result, str) and result.startswith(_NODATA_PREFIXES)


# --- per-category fetchers (patched in tests) -----------------------------

def _fetch_news(ticker: str, trade_date: str):
    end = datetime.strptime(trade_date, "%Y-%m-%d")
    start = (end - relativedelta(days=7)).strftime("%Y-%m-%d")
    # 类型感知分流:ETF→get_etf_news(基金+主题+持仓聚合),股票→get_news(个股)。
    method = "get_etf_news" if resolve_symbol_type(ticker) == "etf" else "get_news"
    result = route_to_vendor(method, ticker, start, trade_date)
    if _is_nodata(result):
        return result
    return {"text": result}


def _fetch_intraday(ticker: str, trade_date: str):
    return get_etf_intraday(ticker, trade_date)


def _fetch_indicators(ticker: str, trade_date: str, lookback: int):
    kline = get_etf_daily_kline(ticker, trade_date, lookback=lookback)
    sections = []
    for ind in _PREFETCH_INDICATORS:
        # get_indicators(symbol, indicator, curr_date, look_back_days)
        text = route_to_vendor("get_indicators", ticker, ind, trade_date, lookback)
        if not _is_nodata(text):
            sections.append(f"## {ind}\n{text}")
    indicator_text = "\n\n".join(sections) if sections else None
    return {"kline": kline["kline"], "indicator_text": indicator_text}


def _fetch_fundamentals(ticker: str, trade_date: str):
    return get_etf_fundamentals_kv(ticker, trade_date)


def _run_with_retry(fn, retries: int, backoff_base: float, sleep) -> tuple[str, dict]:
    """Return (status, payload). Never raises. NO_DATA is not retried."""
    attempt = 0
    while True:
        attempt += 1
        try:
            result = fn()
        except NoMarketDataError:
            return "missing", {}
        except Exception:  # noqa: BLE001 - transient; retry then give up
            if attempt >= retries:
                return "missing", {}
            if backoff_base:
                sleep(backoff_base * (2 ** (attempt - 1)))
            continue
        if _is_nodata(result):
            return "missing", {}
        if not isinstance(result, dict) or not result:
            return "missing", {}
        return "ok", result


def prefetch_snapshot(ticker, trade_date, store, *, config=None, sleep=time.sleep) -> SnapshotSummary:
    config = config or get_config()
    retries = int(config.get("prefetch_retries", 3))
    backoff = float(config.get("prefetch_backoff_base", 1.0))
    lookback = int(config.get("prefetch_daily_lookback", 60))

    fetchers = {
        "news": lambda: _fetch_news(ticker, trade_date),
        "intraday": lambda: _fetch_intraday(ticker, trade_date),
        "indicators": lambda: _fetch_indicators(ticker, trade_date, lookback),
        "fundamentals": lambda: _fetch_fundamentals(ticker, trade_date),
    }

    results: list[CategoryResult] = []
    for category in _CATEGORIES:
        status, payload = _run_with_retry(fetchers[category], retries, backoff, sleep)
        store.upsert_snapshot(ticker, trade_date, category, status, payload)
        results.append(CategoryResult(category=category, status=status, payload=payload))

    return SnapshotSummary(ticker=ticker, trade_date=trade_date, results=results)
