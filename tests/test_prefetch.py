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


def test_fetch_indicators_calls_get_indicators_with_full_signature(monkeypatch):
    # 回归:_fetch_indicators 之前少传 look_back_days 且把日期塞进 indicator 位,
    # 触发 "missing 1 required positional argument: 'look_back_days'"。
    seen = []

    def fake_route(method, *a, **k):
        seen.append((method, a))
        return f"{a[1]} body"  # a = (ticker, indicator, curr_date, look_back_days)

    monkeypatch.setattr(prefetch, "get_etf_daily_kline", lambda t, d, lookback: {"kline": [1, 2]})
    monkeypatch.setattr(prefetch, "route_to_vendor", fake_route)

    result = prefetch._fetch_indicators("510300.SS", "2026-07-07", 60)

    # 每个核心指标都以 4 个位置参数正确调用 get_indicators
    assert [m for m, _ in seen] == ["get_indicators"] * len(prefetch._PREFETCH_INDICATORS)
    for (_, args), ind in zip(seen, prefetch._PREFETCH_INDICATORS, strict=True):
        assert args == ("510300.SS", ind, "2026-07-07", 60)
    assert result["kline"] == [1, 2]
    for ind in prefetch._PREFETCH_INDICATORS:
        assert f"## {ind}" in result["indicator_text"]


def test_fetch_indicators_skips_nodata_and_none_when_all_missing(monkeypatch):
    monkeypatch.setattr(prefetch, "get_etf_daily_kline", lambda t, d, lookback: {"kline": []})
    monkeypatch.setattr(
        prefetch, "route_to_vendor", lambda method, *a, **k: "NO_DATA_AVAILABLE: none"
    )
    result = prefetch._fetch_indicators("510300.SS", "2026-07-07", 60)
    assert result["indicator_text"] is None
