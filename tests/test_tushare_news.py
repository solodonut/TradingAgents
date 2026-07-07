from __future__ import annotations

from unittest import mock

import pandas as pd
import pytest

from tradingagents.dataflows import tushare_news
from tradingagents.dataflows.errors import NoMarketDataError


@pytest.fixture(autouse=True)
def _bypass_cache(monkeypatch):
    # cached_call 会写磁盘并跨用例命中;单测里直接透传,隔离每个用例。
    monkeypatch.setattr(tushare_news, "cached_call", lambda key, ttl, fn: fn())


def _fake_client(anns=None, news=None):
    client = mock.Mock()
    client.anns_d = mock.Mock(return_value=anns if anns is not None else pd.DataFrame())
    client.news = mock.Mock(return_value=news if news is not None else pd.DataFrame())
    return client


@pytest.mark.unit
def test_get_news_non_a_share_raises():
    with pytest.raises(NoMarketDataError):
        tushare_news.get_news("AAPL", "2026-06-01", "2026-06-30")


@pytest.mark.unit
def test_get_news_merges_announcements_and_flash(monkeypatch):
    anns = pd.DataFrame(
        [{"ann_date": "20260610", "title": "贵州茅台业绩预告", "url": "http://x/1.pdf"}]
    )
    news = pd.DataFrame(
        [
            {"datetime": "2026-06-12 09:00:00", "title": "茅台涨停", "content": "贵州茅台大涨"},
            {"datetime": "2026-06-12 09:05:00", "title": "无关新闻", "content": "别的公司"},
        ]
    )
    monkeypatch.setattr(tushare_news, "get_tushare_client", lambda: _fake_client(anns, news))
    monkeypatch.setattr(tushare_news, "resolve_ticker_name", lambda code: "贵州茅台")

    out = tushare_news.get_news("600519.SH", "2026-06-01", "2026-06-30")

    assert out.startswith("## 600519.SS News, from 2026-06-01 to 2026-06-30:")
    assert "业绩预告 (source: 公司公告)" in out
    assert "Link: http://x/1.pdf" in out
    assert "茅台涨停" in out          # 命中关键词的快讯保留
    assert "无关新闻" not in out       # 未命中的快讯被过滤
    # 公告排在快讯之前
    assert out.index("业绩预告") < out.index("茅台涨停")


@pytest.mark.unit
def test_get_news_name_lookup_failure_uses_announcements_only(monkeypatch):
    anns = pd.DataFrame([{"ann_date": "20260610", "title": "公告A", "url": "http://x/a.pdf"}])
    news = pd.DataFrame([{"datetime": "2026-06-12 09:00:00", "title": "某新闻", "content": "内容"}])
    monkeypatch.setattr(tushare_news, "get_tushare_client", lambda: _fake_client(anns, news))
    monkeypatch.setattr(tushare_news, "resolve_ticker_name", lambda code: None)

    out = tushare_news.get_news("600519.SH", "2026-06-01", "2026-06-30")

    assert "公告A" in out
    assert "某新闻" not in out          # 无关键词 -> 快讯路跳过


@pytest.mark.unit
def test_get_news_one_path_failure_degrades(monkeypatch):
    client = mock.Mock()
    client.anns_d = mock.Mock(side_effect=Exception("anns down"))
    client.news = mock.Mock(
        return_value=pd.DataFrame(
            [{"datetime": "2026-06-12 09:00:00", "title": "茅台新闻", "content": "贵州茅台"}]
        )
    )
    monkeypatch.setattr(tushare_news, "get_tushare_client", lambda: client)
    monkeypatch.setattr(tushare_news, "resolve_ticker_name", lambda code: "贵州茅台")

    out = tushare_news.get_news("600519.SH", "2026-06-01", "2026-06-30")

    assert "茅台新闻" in out            # 公告挂了,快讯仍返回
    assert not out.startswith("Error fetching news")


@pytest.mark.unit
def test_get_news_both_paths_fail_returns_sentinel(monkeypatch):
    client = mock.Mock()
    client.anns_d = mock.Mock(side_effect=Exception("anns down"))
    client.news = mock.Mock(side_effect=Exception("news down"))
    monkeypatch.setattr(tushare_news, "get_tushare_client", lambda: client)
    monkeypatch.setattr(tushare_news, "resolve_ticker_name", lambda code: "贵州茅台")

    out = tushare_news.get_news("600519.SH", "2026-06-01", "2026-06-30")

    assert out.startswith("Error fetching news for 600519.SS")


@pytest.mark.unit
def test_get_news_lookahead_filter(monkeypatch):
    anns = pd.DataFrame()
    news = pd.DataFrame(
        [
            {"datetime": "2026-06-15 09:00:00", "title": "窗口内茅台", "content": "贵州茅台"},
            {"datetime": "2026-07-20 09:00:00", "title": "未来茅台", "content": "贵州茅台"},
        ]
    )
    monkeypatch.setattr(tushare_news, "get_tushare_client", lambda: _fake_client(anns, news))
    monkeypatch.setattr(tushare_news, "resolve_ticker_name", lambda code: "贵州茅台")

    out = tushare_news.get_news("600519.SH", "2026-06-01", "2026-06-30")

    assert "窗口内茅台" in out
    assert "未来茅台" not in out        # end_date 之后的被丢弃


@pytest.mark.unit
def test_get_news_empty_returns_no_news(monkeypatch):
    monkeypatch.setattr(
        tushare_news, "get_tushare_client", lambda: _fake_client(pd.DataFrame(), pd.DataFrame())
    )
    monkeypatch.setattr(tushare_news, "resolve_ticker_name", lambda code: "贵州茅台")

    out = tushare_news.get_news("600519.SH", "2026-06-01", "2026-06-30")

    assert out == "No news found for 600519.SS between 2026-06-01 and 2026-06-30"


@pytest.mark.unit
def test_get_news_midnight_boundary_excluded(monkeypatch):
    """end_date 次日 00:00:00 的快讯必须被过滤掉(前视泄漏防护)。"""
    anns = pd.DataFrame()
    news = pd.DataFrame(
        [
            {"datetime": "2026-06-30 23:59:59", "title": "窗口最后一秒", "content": "贵州茅台"},
            {"datetime": "2026-07-01 00:00:00", "title": "次日午夜跨日", "content": "贵州茅台"},
        ]
    )
    monkeypatch.setattr(tushare_news, "get_tushare_client", lambda: _fake_client(anns, news))
    monkeypatch.setattr(tushare_news, "resolve_ticker_name", lambda code: "贵州茅台")

    out = tushare_news.get_news("600519.SH", "2026-06-01", "2026-06-30")

    assert "窗口最后一秒" in out       # end_date 当天最后一秒应保留
    assert "次日午夜跨日" not in out   # end_date+1 00:00:00 应被排除
