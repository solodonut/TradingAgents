import pandas as pd
import pytest

import tradingagents.dataflows.ticker_name as tn

# 真实实现的引用，不受下面 autouse stub 影响（用于直接测试 _tushare_name 本身）。
_real_tushare_name = tn._tushare_name


@pytest.fixture(autouse=True)
def _stub_tushare(monkeypatch):
    # 默认让 tushare 名称源返回 None；单独测 tushare 的用例再覆盖。
    monkeypatch.setattr(tn, "_tushare_name", lambda code: None)


def test_a_share_prefers_tushare_chinese_name(monkeypatch):
    monkeypatch.setattr(tn, "_tushare_name", lambda code: "国防ETF")
    monkeypatch.setattr(tn, "_akshare_name", lambda code: "should-not-be-used")
    monkeypatch.setattr(tn, "_yfinance_name", lambda code: "should-not-be-used")
    assert tn.resolve_ticker_name("159241") == "国防ETF"


def test_a_share_falls_back_to_akshare_when_tushare_empty(monkeypatch):
    monkeypatch.setattr(tn, "_akshare_name", lambda code: "贵州茅台")
    monkeypatch.setattr(tn, "_yfinance_name", lambda code: "should-not-be-used")
    assert tn.resolve_ticker_name("600519.SS") == "贵州茅台"


def test_a_share_falls_back_to_yfinance_when_tushare_and_akshare_empty(monkeypatch):
    monkeypatch.setattr(tn, "_akshare_name", lambda code: None)
    monkeypatch.setattr(tn, "_yfinance_name", lambda code: "Kweichow Moutai")
    assert tn.resolve_ticker_name("600519.SS") == "Kweichow Moutai"


def test_bare_a_share_fallback_uses_yahoo_suffix(monkeypatch):
    seen = []
    monkeypatch.setattr(tn, "_akshare_name", lambda code: None)

    def fake_yfinance(code):
        seen.append(code)
        return "China Southern CSI Semicon Idsty CstmETF"

    monkeypatch.setattr(tn, "_yfinance_name", fake_yfinance)

    assert tn.resolve_ticker_name("159325") == "China Southern CSI Semicon Idsty CstmETF"
    assert seen == ["159325.SZ"]


def test_a_share_falls_back_when_tushare_and_akshare_raise(monkeypatch):
    def boom(code):
        raise RuntimeError("vendor down")

    monkeypatch.setattr(tn, "_tushare_name", boom)
    monkeypatch.setattr(tn, "_akshare_name", boom)
    monkeypatch.setattr(tn, "_yfinance_name", lambda code: "Kweichow Moutai")
    assert tn.resolve_ticker_name("600519.SS") == "Kweichow Moutai"


def test_non_a_share_skips_china_sources_uses_yfinance(monkeypatch):
    called = {"ts": False, "ak": False}

    def ts_name(code):
        called["ts"] = True
        return "nope"

    def ak(code):
        called["ak"] = True
        return "nope"

    monkeypatch.setattr(tn, "_tushare_name", ts_name)
    monkeypatch.setattr(tn, "_akshare_name", ak)
    monkeypatch.setattr(tn, "_yfinance_name", lambda code: "NVIDIA Corporation")
    assert tn.resolve_ticker_name("NVDA") == "NVIDIA Corporation"
    assert called["ts"] is False  # 非 A 股不应触发 tushare
    assert called["ak"] is False  # 非 A 股不应触发 AKShare


def test_returns_none_when_all_sources_miss(monkeypatch):
    monkeypatch.setattr(tn, "_akshare_name", lambda code: None)
    monkeypatch.setattr(tn, "_yfinance_name", lambda code: None)
    assert tn.resolve_ticker_name("ZZZZ") is None


def test_tushare_timeout_falls_back(monkeypatch):
    import time

    def slow(code):
        time.sleep(5)  # 远超下面设的超时
        return "迟到的名字"

    monkeypatch.setattr(tn, "_tushare_name", slow)
    monkeypatch.setattr(tn, "_akshare_name", lambda code: None)
    monkeypatch.setattr(tn, "_NAME_LOOKUP_TIMEOUT_S", 0.2)
    monkeypatch.setattr(tn, "_yfinance_name", lambda code: "Kweichow Moutai")
    assert tn.resolve_ticker_name("600519.SS") == "Kweichow Moutai"


def test_tushare_name_reads_fund_basic_name(monkeypatch):
    import tradingagents.dataflows.tushare_utils as tu

    class FakeClient:
        def fund_basic(self, ts_code):
            return pd.DataFrame([{"ts_code": ts_code, "name": "国防ETF"}])

    monkeypatch.setattr(tu, "get_tushare_client", lambda: FakeClient())
    monkeypatch.setattr(tu, "cached_call", lambda key, ttl, func: func())
    assert _real_tushare_name("159241") == "国防ETF"


def test_tushare_name_reads_stock_basic_name(monkeypatch):
    import tradingagents.dataflows.tushare_utils as tu

    class FakeClient:
        def stock_basic(self, ts_code):
            return pd.DataFrame([{"ts_code": ts_code, "name": "贵州茅台"}])

    monkeypatch.setattr(tu, "get_tushare_client", lambda: FakeClient())
    monkeypatch.setattr(tu, "cached_call", lambda key, ttl, func: func())
    assert _real_tushare_name("600519.SS") == "贵州茅台"
