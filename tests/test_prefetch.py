from tradingagents.dataflows import prefetch


class FakeStore:
    def __init__(self):
        self.rows = {}

    def upsert_snapshot(self, ticker, trade_date, category, status, payload):
        self.rows[category] = (status, payload)


def _cfg():
    return {"prefetch_retries": 2, "prefetch_backoff_base": 0.0, "prefetch_daily_lookback": 60}


def test_prefetch_all_ok(monkeypatch):
    monkeypatch.setattr(prefetch, "_fetch_news", lambda t, d: {"text": "news"})
    monkeypatch.setattr(prefetch, "_fetch_intraday", lambda t, d: {"points": [1]})
    monkeypatch.setattr(prefetch, "_fetch_indicators", lambda t, d, lb: {"kline": [1]})
    monkeypatch.setattr(prefetch, "_fetch_fundamentals", lambda t, d: {"items": [1]})
    store = FakeStore()
    summary = prefetch.prefetch_snapshot(
        "510300.SS", "2026-07-07", store, config=_cfg(), sleep=lambda s: None
    )
    assert {r.category: r.status for r in summary.results} == {
        "news": "ok", "intraday": "ok", "indicators": "ok", "fundamentals": "ok"
    }
    assert store.rows["news"][0] == "ok"


def test_prefetch_marks_missing_on_persistent_error(monkeypatch):
    calls = {"n": 0}

    def boom(t, d):
        calls["n"] += 1
        raise TimeoutError("rate limited")

    monkeypatch.setattr(prefetch, "_fetch_news", boom)
    monkeypatch.setattr(
        prefetch,
        "_fetch_intraday",
        lambda t, d: {"points": [{"t": "15:00", "price": 4.82, "vol": 1.0}]},
    )
    monkeypatch.setattr(prefetch, "_fetch_indicators", lambda t, d, lb: {"kline": [1]})
    monkeypatch.setattr(prefetch, "_fetch_fundamentals", lambda t, d: {"items": [1]})
    store = FakeStore()
    summary = prefetch.prefetch_snapshot(
        "510300.SS", "2026-07-07", store, config=_cfg(), sleep=lambda s: None
    )
    news = next(r for r in summary.results if r.category == "news")
    assert news.status == "missing"
    assert calls["n"] == 2  # retries 用尽(prefetch_retries=2)
    ctx = summary.for_context()
    assert "news" in ctx["missing"]
    assert ctx["quote"]["last_price"] == 4.82  # 分时成功 → quote 从末点取价


def test_prefetch_no_data_not_retried(monkeypatch):
    calls = {"n": 0}

    def nodata(t, d):
        calls["n"] += 1
        return "NO_DATA_AVAILABLE: none"

    monkeypatch.setattr(prefetch, "_fetch_news", nodata)
    monkeypatch.setattr(prefetch, "_fetch_intraday", lambda t, d: {"points": [1]})
    monkeypatch.setattr(prefetch, "_fetch_indicators", lambda t, d, lb: {"kline": [1]})
    monkeypatch.setattr(prefetch, "_fetch_fundamentals", lambda t, d: {"items": [1]})
    store = FakeStore()
    summary = prefetch.prefetch_snapshot(
        "510300.SS", "2026-07-07", store, config=_cfg(), sleep=lambda s: None
    )
    news = next(r for r in summary.results if r.category == "news")
    assert news.status == "missing"
    assert calls["n"] == 1  # NO_DATA 不重试


def test_prefetch_never_raises(monkeypatch):
    monkeypatch.setattr(prefetch, "_fetch_news", lambda t, d: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(prefetch, "_fetch_intraday", lambda t, d: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(prefetch, "_fetch_indicators", lambda t, d, lb: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(prefetch, "_fetch_fundamentals", lambda t, d: (_ for _ in ()).throw(RuntimeError("x")))
    store = FakeStore()
    summary = prefetch.prefetch_snapshot(
        "510300.SS", "2026-07-07", store, config=_cfg(), sleep=lambda s: None
    )
    assert all(r.status == "missing" for r in summary.results)


def test_fetch_news_routes_by_type(monkeypatch):
    seen = []

    def fake_route(method, *a, **k):
        seen.append(method)
        return "news body"

    monkeypatch.setattr(prefetch, "route_to_vendor", fake_route)
    prefetch._fetch_news("510300.SS", "2026-07-07")  # ETF → get_etf_news
    prefetch._fetch_news("600519.SS", "2026-07-07")  # 股票 → get_news
    assert seen == ["get_etf_news", "get_news"]
