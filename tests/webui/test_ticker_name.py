import tradingagents.dataflows.ticker_name as tn


def test_a_share_prefers_akshare_chinese_name(monkeypatch):
    monkeypatch.setattr(tn, "_akshare_name", lambda code: "贵州茅台")
    monkeypatch.setattr(tn, "_yfinance_name", lambda code: "should-not-be-used")
    assert tn.resolve_ticker_name("600519.SS") == "贵州茅台"


def test_a_share_falls_back_to_yfinance_when_akshare_empty(monkeypatch):
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


def test_a_share_falls_back_to_yfinance_when_akshare_raises(monkeypatch):
    def boom(code):
        raise RuntimeError("east money down")
    monkeypatch.setattr(tn, "_akshare_name", boom)
    monkeypatch.setattr(tn, "_yfinance_name", lambda code: "Kweichow Moutai")
    assert tn.resolve_ticker_name("600519.SS") == "Kweichow Moutai"


def test_non_a_share_skips_akshare_uses_yfinance(monkeypatch):
    called = {"ak": False}
    def ak(code):
        called["ak"] = True
        return "nope"
    monkeypatch.setattr(tn, "_akshare_name", ak)
    monkeypatch.setattr(tn, "_yfinance_name", lambda code: "NVIDIA Corporation")
    assert tn.resolve_ticker_name("NVDA") == "NVIDIA Corporation"
    assert called["ak"] is False  # 非 A 股不应触发 AKShare


def test_returns_none_when_all_sources_miss(monkeypatch):
    monkeypatch.setattr(tn, "_akshare_name", lambda code: None)
    monkeypatch.setattr(tn, "_yfinance_name", lambda code: None)
    assert tn.resolve_ticker_name("ZZZZ") is None


def test_akshare_timeout_falls_back(monkeypatch):
    import time
    def slow(code):
        time.sleep(5)  # 远超下面设的超时
        return "迟到的名字"
    monkeypatch.setattr(tn, "_akshare_name", slow)
    monkeypatch.setattr(tn, "_AKSHARE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(tn, "_yfinance_name", lambda code: "Kweichow Moutai")
    assert tn.resolve_ticker_name("600519.SS") == "Kweichow Moutai"
