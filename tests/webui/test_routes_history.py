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
    store.insert_run("r1", "159915", "2026-06-26", "stock", {"x": 1})
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


def test_delete_history(client):
    _seed(client)
    assert client.delete("/api/history/r1").status_code == 204
    assert client.get("/api/history/r1").status_code == 404
