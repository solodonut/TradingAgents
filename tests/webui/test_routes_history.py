import io
import zipfile


def _seed(client):
    store = client.app.state.store or _force_store(client)
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {"x": 1})
    store.complete_run("r1", decision="Buy", result={"final_trade_decision": "**Rating**: Buy"})
    return store


def _force_store(client):
    import api.main as main

    return main.get_store()


def test_list_history(client):
    _seed(client)
    resp = client.get("/api/history")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["ticker"] == "NVDA"
    assert items[0]["decision"] == "Buy"


def test_list_history_backfills_missing_instrument_name(client, monkeypatch):
    import api.routes.history as history_routes

    store = client.app.state.store or _force_store(client)
    store.insert_run("r1", "159915", "2026-06-26", "stock", {"x": 1})
    store.complete_run("r1", decision="Hold", result={"final_trade_decision": "x"})
    monkeypatch.setattr(
        history_routes, "resolve_ticker_name", lambda ticker: "创业板ETF易方达"
    )

    resp = client.get("/api/history")

    assert resp.status_code == 200
    assert resp.json()[0]["instrument_name"] == "创业板ETF易方达"
    assert store.get_run("r1").instrument_name == "创业板ETF易方达"


def test_get_history_detail(client):
    _seed(client)
    resp = client.get("/api/history/r1")
    assert resp.status_code == 200
    assert resp.json()["result"]["final_trade_decision"] == "**Rating**: Buy"


def test_get_history_detail_backfills_missing_instrument_name(client, monkeypatch):
    import api.routes.history as history_routes

    store = client.app.state.store or _force_store(client)
    store.insert_run(
        "r1",
        "159915",
        "2026-06-26",
        "stock",
        {"x": 1},
        instrument_name="创业板ETF易方达",
    )
    store.complete_run("r1", decision="Hold", result={"final_trade_decision": "x"})
    monkeypatch.setattr(
        history_routes, "resolve_ticker_name", lambda ticker: "创业板ETF易方达"
    )

    resp = client.get("/api/history/r1")

    assert resp.status_code == 200
    assert resp.json()["instrument_name"] == "创业板ETF易方达"


def test_get_missing_returns_404(client):
    resp = client.get("/api/history/nope")
    assert resp.status_code == 404


def test_download_history_reports_zip(client):
    store = client.app.state.store or _force_store(client)
    store.insert_run(
        "r1",
        "159915",
        "2026-06-26",
        "stock",
        {"x": 1},
        instrument_name="创业板ETF易方达",
    )
    store.complete_run(
        "r1",
        decision="Hold",
        result={"market_report": "## Market\nUp", "final_trade_decision": "**Rating**: Hold"},
    )
    store.insert_run("r2", "NVDA", "2026-06-26", "stock", {"x": 1})

    resp = client.get("/api/history/reports.zip")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        assert archive.namelist() == ["159915_创业板ETF易方达_2026-06-26.md"]
        content = archive.read("159915_创业板ETF易方达_2026-06-26.md").decode()
    assert "# TradingAgents 分析报告 — 159915 创业板ETF易方达 (2026-06-26)" in content
    assert "## 市场分析" in content
    assert "**Rating**: Hold" in content


def test_download_history_reports_zip_filters_selected_run_ids(client):
    store = client.app.state.store or _force_store(client)
    store.insert_run(
        "r1",
        "159915",
        "2026-06-26",
        "stock",
        {"x": 1},
        instrument_name="创业板ETF易方达",
    )
    store.complete_run("r1", decision="Hold", result={"final_trade_decision": "one"})
    store.insert_run("r2", "510330", "2026-06-26", "stock", {"x": 1}, instrument_name="华夏沪深300ETF")
    store.complete_run("r2", decision="Buy", result={"final_trade_decision": "two"})
    store.insert_run("r3", "NVDA", "2026-06-25", "stock", {"x": 1})
    store.complete_run("r3", decision="Sell", result={"final_trade_decision": "three"})

    resp = client.get("/api/history/reports.zip?run_ids=r1&run_ids=r3")

    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        names = archive.namelist()
        contents = "\n".join(archive.read(name).decode() for name in names)
    assert names == ["NVDA_2026-06-25.md", "159915_创业板ETF易方达_2026-06-26.md"]
    assert "one" in contents
    assert "three" in contents
    assert "two" not in contents


def test_download_history_reports_zip_returns_404_without_reports(client):
    store = client.app.state.store or _force_store(client)
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {"x": 1})

    resp = client.get("/api/history/reports.zip")

    assert resp.status_code == 404


def test_delete_history(client):
    _seed(client)
    assert client.delete("/api/history/r1").status_code == 204
    assert client.get("/api/history/r1").status_code == 404
