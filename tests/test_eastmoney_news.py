"""East Money direct-search news fallback.

``eastmoney_news.get_news`` mirrors ``akshare_news.get_news`` — it exists so the
router can fall through from AKShare (library-level failure) to the same source
hit directly. These tests pin the parse/filter/format contract with the network
layer mocked, so no live East Money call is made.
"""
import json

import pytest
import requests

import tradingagents.dataflows.eastmoney_news as enews
from tradingagents.dataflows.errors import NoMarketDataError


def _jsonp(articles):
    """Wrap articles the way the East Money JSONP endpoint does: ``x({...})``."""
    payload = {"result": {"cmsArticleWebOld": articles}}
    return "x(" + json.dumps(payload, ensure_ascii=False) + ")"


class _FakeResp:
    def __init__(self, text):
        self._text = text
        self.encoding = None

    def raise_for_status(self):
        pass

    @property
    def text(self):
        return self._text


@pytest.fixture(autouse=True)
def _bypass_cache_and_retry(monkeypatch):
    # Skip the on-disk cache and the proxy-bypass/retry ladder so tests exercise
    # only the parse/filter/format logic against the mocked HTTP layer.
    monkeypatch.setattr(enews, "cached_call", lambda key, ttl, func: func())
    monkeypatch.setattr(enews, "ak_retry", lambda func, **kw: func())


@pytest.mark.unit
def test_returns_formatted_etf_news_within_window(monkeypatch):
    articles = [
        {
            "date": "2025-05-05 10:00:00",
            "title": "沪深<em>300</em>ETF获资金净流入",
            "content": "宽基<em>ETF</em>成为核心抓手",
            "mediaName": "中证网",
            "url": "http://stock.eastmoney.com/a/1.html",
        },
        {
            "date": "2025-06-01 10:00:00",  # after the window -> look-ahead, must drop
            "title": "未来事件",
            "content": "",
            "mediaName": "东财",
            "url": "http://stock.eastmoney.com/a/2.html",
        },
    ]
    monkeypatch.setattr(enews.requests, "get", lambda *a, **k: _FakeResp(_jsonp(articles)))

    out = enews.get_news("510300", "2025-05-01", "2025-05-09")

    assert out.startswith("## 510300.SS News, from 2025-05-01 to 2025-05-09:")
    assert "沪深300ETF获资金净流入 (source: 中证网)" in out  # <em> stripped
    assert "宽基ETF成为核心抓手" in out
    assert "Link: http://stock.eastmoney.com/a/1.html" in out
    assert "未来事件" not in out  # future-dated article excluded


@pytest.mark.unit
def test_non_a_share_raises_to_allow_fallback():
    with pytest.raises(NoMarketDataError):
        enews.get_news("AAPL", "2025-05-01", "2025-05-09")


@pytest.mark.unit
def test_network_error_returns_error_sentinel(monkeypatch):
    def _boom(*a, **k):
        raise requests.exceptions.ConnectionError("connection reset")

    monkeypatch.setattr(enews.requests, "get", _boom)

    out = enews.get_news("510300", "2025-05-01", "2025-05-09")
    # route_to_vendor keys off this exact prefix to try the next vendor.
    assert out.startswith("Error fetching news for 510300.SS:")


@pytest.mark.unit
def test_empty_feed_reports_no_news(monkeypatch):
    monkeypatch.setattr(enews.requests, "get", lambda *a, **k: _FakeResp(_jsonp([])))

    out = enews.get_news("510300", "2025-05-01", "2025-05-09")
    assert out == "No news found for 510300.SS"
    assert "###" not in out
