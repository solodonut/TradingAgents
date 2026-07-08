from __future__ import annotations

from unittest import mock

import pandas as pd
import pytest

from tradingagents.dataflows import interface
from tradingagents.dataflows.config import set_config


@pytest.mark.unit
def test_get_etf_news_renders_sections_limits_and_dedupes(monkeypatch):
    from tradingagents.dataflows import tushare_etf_news

    monkeypatch.setattr(tushare_etf_news, "_fetch_fund_basic", lambda ts_code: pd.DataFrame([
        {"ts_code": ts_code, "name": "沪深300ETF", "benchmark": "沪深300指数"}
    ]))
    monkeypatch.setattr(tushare_etf_news, "_fetch_fund_portfolio", lambda ts_code: pd.DataFrame([
        {"symbol": "600519.SH", "mkv": 100, "amount": 1, "stk_mkv_ratio": 5.2, "stk_name": "贵州茅台", "end_date": "20260331"},
        {"symbol": "601318.SH", "stk_mkv_ratio": 4.1, "stk_name": "中国平安", "end_date": "20260331"},
        {"symbol": "600036.SH", "stk_mkv_ratio": 3.8, "stk_name": "招商银行", "end_date": "20260331"},
        {"symbol": "000858.SZ", "stk_mkv_ratio": 3.1, "stk_name": "五粮液", "end_date": "20260331"},
        {"symbol": "300750.SZ", "stk_mkv_ratio": 2.9, "stk_name": "宁德时代", "end_date": "20260331"},
        {"symbol": "601398.SH", "stk_mkv_ratio": 2.4, "stk_name": "工商银行", "end_date": "20260331"},
    ]))
    monkeypatch.setattr(tushare_etf_news, "_fetch_akshare_holdings", lambda *a, **k: [])

    def fake_stock_news(symbol, start_date, end_date):
        if symbol == "510300.SH":
            return "## 510300.SS News\n\n### ETF公告 (source: 公司公告)\n基金公告\n\n"
        return (
            f"## {symbol} News\n\n"
            "### 重复标题 (source: 快讯)\n重复内容\n\n"
            f"### {symbol} 独有新闻 (source: 快讯)\n内容\n\n"
            f"### {symbol} 第三条 (source: 快讯)\n内容\n\n"
            f"### {symbol} 第四条 (source: 快讯)\n内容\n\n"
        )

    monkeypatch.setattr(tushare_etf_news.tushare_news, "get_news", fake_stock_news)
    monkeypatch.setattr(tushare_etf_news.tushare_news, "_fetch_flash", lambda src, start, end: pd.DataFrame([
        {"datetime": "2026-07-07 09:00:00", "title": "沪深300走强", "content": "沪深300指数上涨"},
        {"datetime": "2026-07-08 10:00:00", "title": "未来新闻", "content": "沪深300指数"},
    ]))

    out = tushare_etf_news.get_etf_news("510300", "2026-07-01", "2026-07-07")

    assert out.startswith("# ETF News for 510300.SS, from 2026-07-01 to 2026-07-07")
    assert "## ETF / Fund-Level News" in out
    assert "ETF公告" in out
    assert "## Index / Theme News" in out
    assert "沪深300走强" in out
    assert "未来新闻" not in out
    assert "## Top Holdings News" in out
    assert out.count("### 60") + out.count("### 00") + out.count("### 30") == 5
    assert "601398" not in out
    assert out.count("重复标题") == 1
    assert "600519.SS 第四条" not in out
    assert "latest disclosed quarter" in out


@pytest.mark.unit
def test_get_etf_news_degrades_when_holdings_unavailable(monkeypatch):
    from tradingagents.dataflows import tushare_etf_news

    monkeypatch.setattr(tushare_etf_news, "_fetch_fund_basic", lambda ts_code: pd.DataFrame([
        {"ts_code": ts_code, "name": "半导体ETF", "benchmark": ""}
    ]))
    monkeypatch.setattr(tushare_etf_news, "_fetch_fund_portfolio", mock.Mock(side_effect=Exception("down")))
    monkeypatch.setattr(tushare_etf_news, "_fetch_akshare_holdings", lambda *a, **k: [])
    monkeypatch.setattr(
        tushare_etf_news.tushare_news,
        "get_news",
        lambda *a, **k: "No news found for 512480.SS between 2026-07-01 and 2026-07-07",
    )
    monkeypatch.setattr(tushare_etf_news.tushare_news, "_fetch_flash", lambda src, start, end: pd.DataFrame([
        {"datetime": "2026-07-06 09:00:00", "title": "半导体反弹", "content": "半导体板块走强"},
    ]))

    out = tushare_etf_news.get_etf_news("512480", "2026-07-01", "2026-07-07")

    assert "## ETF / Fund-Level News" in out
    assert "No ETF/fund-level news found" in out
    assert "半导体反弹" in out
    assert "Top holdings unavailable" in out
    assert "Missing sections: ETF/fund-level news, top holdings" in out


@pytest.mark.unit
def test_get_etf_news_one_holding_failure_continues(monkeypatch):
    from tradingagents.dataflows import tushare_etf_news

    monkeypatch.setattr(tushare_etf_news, "_fetch_fund_basic", lambda ts_code: pd.DataFrame([
        {"ts_code": ts_code, "name": "沪深300ETF", "benchmark": "沪深300"}
    ]))
    monkeypatch.setattr(tushare_etf_news, "_fetch_fund_portfolio", lambda ts_code: pd.DataFrame([
        {"symbol": "600519.SH", "stk_mkv_ratio": 5.2, "stk_name": "贵州茅台", "end_date": "20260331"},
        {"symbol": "601318.SH", "stk_mkv_ratio": 4.1, "stk_name": "中国平安", "end_date": "20260331"},
    ]))
    monkeypatch.setattr(tushare_etf_news, "_fetch_akshare_holdings", lambda *a, **k: [])
    monkeypatch.setattr(tushare_etf_news.tushare_news, "_fetch_flash", lambda *a, **k: pd.DataFrame())

    def fake_stock_news(symbol, *args):
        if symbol == "600519.SS":
            raise RuntimeError("holding news down")
        return f"## {symbol} News\n\n### 平安新闻 (source: 快讯)\n内容\n\n"

    monkeypatch.setattr(tushare_etf_news.tushare_news, "get_news", fake_stock_news)

    out = tushare_etf_news.get_etf_news("510300", "2026-07-01", "2026-07-07")

    assert "600519.SS 贵州茅台" in out
    assert "Holding news unavailable: holding news down" in out
    assert "601318.SS 中国平安" in out
    assert "平安新闻" in out


@pytest.mark.unit
def test_get_etf_news_uses_latest_disclosed_quarter_once_per_holding(monkeypatch):
    from tradingagents.dataflows import tushare_etf_news

    monkeypatch.setattr(tushare_etf_news, "_fetch_fund_basic", lambda ts_code: pd.DataFrame([
        {"ts_code": ts_code, "name": "沪深300ETF", "benchmark": "沪深300"}
    ]))
    monkeypatch.setattr(tushare_etf_news, "_fetch_fund_portfolio", lambda ts_code: pd.DataFrame([
        {"symbol": "601318.SH", "stk_mkv_ratio": 7.75, "stk_name": "中国平安", "end_date": "20260331"},
        {"symbol": "600519.SH", "stk_mkv_ratio": 5.20, "stk_name": "贵州茅台", "end_date": "20260331"},
        {"symbol": "601318.SH", "stk_mkv_ratio": 7.62, "stk_name": "中国平安", "end_date": "20251231"},
    ]))
    monkeypatch.setattr(tushare_etf_news, "_fetch_akshare_holdings", lambda *a, **k: [])
    monkeypatch.setattr(tushare_etf_news.tushare_news, "_fetch_flash", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(
        tushare_etf_news.tushare_news,
        "get_news",
        lambda symbol, *args: f"## {symbol} News\n\n### {symbol} 新闻 (source: 快讯)\n内容\n\n",
    )

    out = tushare_etf_news.get_etf_news("510300", "2026-07-01", "2026-07-07")

    assert out.count("### 601318.SS 中国平安") == 1
    assert "weight 7.75%" in out
    assert "weight 7.62%" not in out
    assert "latest disclosed quarter (20260331)" in out


@pytest.mark.unit
def test_get_etf_news_backfills_names_and_normalizes_shanghai_suffix(monkeypatch):
    """Real fund_portfolio has NO name column and yields Shanghai `.SH` symbols.

    Regression for the report showing 持仓名称 = "-" and empty holdings news:
    names must be backfilled via resolve_ticker_name, and Shanghai symbols must
    be normalized to the `.SS` form the downstream news/name lookups accept.
    """
    from tradingagents.dataflows import tushare_etf_news

    # Real schema: symbol + stk_mkv_ratio + end_date only, NO name column.
    monkeypatch.setattr(tushare_etf_news, "_fetch_fund_basic", lambda ts_code: pd.DataFrame([
        {"ts_code": ts_code, "name": "沪深300ETF", "benchmark": "沪深300指数"}
    ]))
    monkeypatch.setattr(tushare_etf_news, "_fetch_fund_portfolio", lambda ts_code: pd.DataFrame([
        {"symbol": "600519.SH", "mkv": 100, "stk_mkv_ratio": 3.74, "end_date": "20260331"},
        {"symbol": "300750.SZ", "mkv": 90, "stk_mkv_ratio": 4.37, "end_date": "20260331"},
    ]))
    monkeypatch.setattr(tushare_etf_news, "_fetch_akshare_holdings", lambda *a, **k: [])
    monkeypatch.setattr(tushare_etf_news, "resolve_ticker_name", lambda sym: {
        "600519.SS": "贵州茅台",
        "300750.SZ": "宁德时代",
    }.get(sym))
    monkeypatch.setattr(tushare_etf_news.tushare_news, "_fetch_flash", lambda *a, **k: pd.DataFrame())

    seen_symbols = []

    def fake_stock_news(symbol, *args):
        seen_symbols.append(symbol)
        return f"## {symbol} News\n\n### {symbol} 新闻 (source: 快讯)\n内容\n\n"

    monkeypatch.setattr(tushare_etf_news.tushare_news, "get_news", fake_stock_news)

    out = tushare_etf_news.get_etf_news("510300", "2026-07-01", "2026-07-07")

    # Shanghai holding normalized to .SS and its name backfilled.
    assert "600519.SS 贵州茅台" in out
    assert "300750.SZ 宁德时代" in out
    # Downstream news lookup received the .SS form (not the rejected .SH).
    assert "600519.SS" in seen_symbols
    assert "600519.SH" not in seen_symbols


@pytest.mark.unit
def test_get_etf_news_generic_flash_titles_not_collapsed_across_holdings(monkeypatch):
    """Real sina flash items have empty titles → all render as `### 快讯`.

    Regression: the shared seen-set + `###`-line dedup key collapsed every
    holding's flash news to nothing once the theme step consumed one `快讯`
    block. Distinct-body flash items must survive per holding.
    """
    from tradingagents.dataflows import tushare_etf_news

    monkeypatch.setattr(tushare_etf_news, "_fetch_fund_basic", lambda ts_code: pd.DataFrame([
        {"ts_code": ts_code, "name": "沪深300ETF", "benchmark": "沪深300指数"}
    ]))
    monkeypatch.setattr(tushare_etf_news, "_fetch_fund_portfolio", lambda ts_code: pd.DataFrame([
        {"symbol": "600519.SH", "stk_mkv_ratio": 3.74, "stk_name": "贵州茅台", "end_date": "20260331"},
        {"symbol": "300750.SZ", "stk_mkv_ratio": 4.37, "stk_name": "宁德时代", "end_date": "20260331"},
    ]))
    monkeypatch.setattr(tushare_etf_news, "_fetch_akshare_holdings", lambda *a, **k: [])
    monkeypatch.setattr(tushare_etf_news, "resolve_ticker_name", lambda sym: None)
    # Theme flash: empty title → renders as generic `### 快讯`, seeding the key.
    monkeypatch.setattr(tushare_etf_news.tushare_news, "_fetch_flash", lambda *a, **k: pd.DataFrame([
        {"datetime": "2026-07-06 09:00:00", "title": "", "content": "沪深300指数震荡收涨"},
    ]))

    def fake_stock_news(symbol, *args):
        # Each holding gets a DISTINCT-body flash rendered with the generic
        # `### 快讯` header (mirrors real sina flash with empty title fields).
        return f"## {symbol} News\n\n### 快讯 (source: 快讯)\n【{symbol} 专属公告】要点\n\n"

    monkeypatch.setattr(tushare_etf_news.tushare_news, "get_news", fake_stock_news)

    out = tushare_etf_news.get_etf_news("510300", "2026-07-01", "2026-07-07")

    # Both holdings' distinct flash bodies must survive the shared dedup set.
    assert "600519.SS 专属公告" in out
    assert "300750.SZ 专属公告" in out


@pytest.mark.unit
def test_route_get_etf_news_hits_tushare(monkeypatch):
    from tradingagents.dataflows import tushare_etf_news

    set_config({"tool_vendors": {"get_etf_news": "tushare"}})
    called = {}

    def fake_etf_news(symbol, start_date, end_date):
        called["args"] = (symbol, start_date, end_date)
        return "ETF_NEWS"

    monkeypatch.setattr(tushare_etf_news, "get_etf_news", fake_etf_news)
    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {"get_etf_news": {"tushare": fake_etf_news}},
        clear=False,
    ):
        result = interface.route_to_vendor("get_etf_news", "510300", "2026-07-01", "2026-07-07")

    assert result == "ETF_NEWS"
    assert called["args"] == ("510300", "2026-07-01", "2026-07-07")
