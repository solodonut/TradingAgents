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


def test_log_view_route_returns_timeline_summary(tmp_path, monkeypatch):
    import api.main as main

    store = Store(tmp_path / "webui.db")
    monkeypatch.setattr(main, "get_store", lambda: store)

    store.enqueue_run(
        run_id="r1", ticker="SPY", trade_date="2026-07-03",
        asset_type="stock", config={},
    )
    log_file = tmp_path / "SPY_1.jsonl"
    log_file.write_text(
        "\n".join([
            '{"ts":"2026-07-03T00:00:00+00:00","seq":1,"run_id":"r1","event_type":"run_start","ticker":"SPY"}',
            '{"ts":"2026-07-03T00:00:02+00:00","seq":2,"run_id":"r1","event_type":"llm_call","elapsed_ms":1500,"model":"gpt-test","response":"ok"}',
            '{"ts":"2026-07-03T00:00:03+00:00","seq":3,"run_id":"r1","event_type":"node_exit","elapsed_ms":3000,"node":"Trader"}',
            '{"ts":"2026-07-03T00:00:04+00:00","seq":4,"run_id":"r1","event_type":"vendor_call","elapsed_ms":250,"method":"get_stock_data","vendor":"tushare","ok":true}',
            '{"ts":"2026-07-03T00:00:05+00:00","seq":5,"run_id":"r1","event_type":"run_end","decision":"Hold"}',
        ]) + "\n",
        encoding="utf-8",
    )
    store.set_log_path("r1", str(log_file))

    client = TestClient(main.app)
    resp = client.get("/api/analysis/r1/logs/view")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "r1"
    assert body["elapsed_label"] == "5.0 s"
    assert body["event_counts"]["llm_call"] == 1
    assert body["duration_totals"]["llm_call"] == 1500
    assert body["node_totals"][0]["label"] == "Trader"
    assert body["node_totals"][0]["duration_ms"] == 3000
    assert body["timeline"][0]["label"] == "gpt-test"
    assert body["timeline"][0]["start_ms"] == 500
    assert body["slow_events"][0]["label"] == "Trader"


def test_log_view_route_summarizes_errors(tmp_path, monkeypatch):
    import api.main as main

    store = Store(tmp_path / "webui.db")
    monkeypatch.setattr(main, "get_store", lambda: store)

    store.insert_run(run_id="r1", ticker="SPY", trade_date="2026-07-03",
                     asset_type="stock", config={})
    store.mark_error("r1", "runner exploded")
    log_file = tmp_path / "SPY_1.jsonl"
    log_file.write_text(
        "\n".join([
            '{"ts":"2026-07-03T00:00:00+00:00","seq":1,"run_id":"r1","event_type":"run_start","ticker":"SPY"}',
            '{"ts":"2026-07-03T00:00:01+00:00","seq":2,"run_id":"r1","event_type":"error","node":"Trader","error":"provider timeout"}',
            '{"ts":"2026-07-03T00:00:02+00:00","seq":3,"run_id":"r1","event_type":"vendor_call","elapsed_ms":800,"method":"get_news","vendor":"akshare","ok":false,"error":"HTTP 500"}',
        ]) + "\n",
        encoding="utf-8",
    )
    store.set_log_path("r1", str(log_file))

    client = TestClient(main.app)
    resp = client.get("/api/analysis/r1/logs/view")
    assert resp.status_code == 200
    errors = resp.json()["errors"]
    assert errors == [
        {"seq": 2, "source": "Trader", "message": "provider timeout"},
        {"seq": 3, "source": "get_news / akshare", "message": "HTTP 500"},
        {"seq": None, "source": "run_result", "message": "runner exploded"},
    ]


def test_logs_route_404_when_missing(tmp_path, monkeypatch):
    import api.main as main

    store = Store(tmp_path / "webui.db")
    monkeypatch.setattr(main, "get_store", lambda: store)
    client = TestClient(main.app)
    assert client.get("/api/analysis/unknown/logs").status_code == 404
