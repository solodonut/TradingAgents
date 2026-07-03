from fastapi.testclient import TestClient

from api.store import Store


def test_set_and_get_log_path(tmp_path):
    store = Store(tmp_path / "webui.db")
    store.enqueue_run(
        run_id="r1", ticker="SPY", trade_date="2026-07-03",
        asset_type="stock", config={},
    )
    assert store.get_log_path("r1") is None
    store.set_log_path("r1", "/tmp/x/SPY_1.jsonl")
    assert store.get_log_path("r1") == "/tmp/x/SPY_1.jsonl"


def test_get_log_path_unknown_run(tmp_path):
    store = Store(tmp_path / "webui.db")
    assert store.get_log_path("nope") is None


def test_logs_route_returns_events(tmp_path, monkeypatch):
    import api.main as main

    store = Store(tmp_path / "webui.db")
    monkeypatch.setattr(main, "get_store", lambda: store)

    store.enqueue_run(run_id="r1", ticker="SPY", trade_date="2026-07-03",
                      asset_type="stock", config={})
    log_file = tmp_path / "SPY_1.jsonl"
    log_file.write_text('{"seq":1,"event_type":"run_start"}\n{"seq":2,"event_type":"run_end"}\n',
                        encoding="utf-8")
    store.set_log_path("r1", str(log_file))

    client = TestClient(main.app)
    resp = client.get("/api/analysis/r1/logs")
    assert resp.status_code == 200
    body = resp.json()
    assert [e["event_type"] for e in body["events"]] == ["run_start", "run_end"]


def test_logs_route_404_when_missing(tmp_path, monkeypatch):
    import api.main as main

    store = Store(tmp_path / "webui.db")
    monkeypatch.setattr(main, "get_store", lambda: store)
    client = TestClient(main.app)
    assert client.get("/api/analysis/unknown/logs").status_code == 404
