import threading
import time


def _wait_until(client, predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _set_parallelism(value: int) -> None:
    import api.main as main
    from api.scheduler import MAX_PARALLEL_SETTING

    main.get_store().set_setting(MAX_PARALLEL_SETTING, str(value))


def _install_gated_graph(client, gate: threading.Event, max_parallel: int = 1):
    """Install a fake graph that blocks mid-stream until ``gate`` is set.

    Pins the parallel-run limit (default 1) so each test knows exactly how many
    of the enqueued runs get launched and how many stay pending.
    """
    import types

    import api.main as main

    _set_parallelism(max_parallel)

    def factory(req):
        class _Inner:
            def stream(inner_self, init_state, **kwargs):
                yield {"market_report": "m"}
                gate.wait(timeout=5)
                yield {"final_trade_decision": "**Rating**: Hold"}

        return types.SimpleNamespace(graph=_Inner()), {}, "Hold", {"final_trade_decision": "x"}

    main.app.state.graph_factory = factory


def test_enqueue_returns_running_and_pending(client):
    import api.main as main

    gate = threading.Event()
    _install_gated_graph(client, gate)

    resp = client.post(
        "/api/queue",
        json={"tickers": ["NVDA", "AAPL", "TSLA"], "trade_date": "2024-05-10"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["run_ids"]) == 3
    assert len(body["running_run_ids"]) == 1

    # first is running, other two pending
    assert _wait_until(client, lambda: main.get_store().list_queue().running != [])
    state = main.get_store().list_queue()
    assert [r.ticker for r in state.running] == ["NVDA"]
    assert [p.ticker for p in state.pending] == ["AAPL", "TSLA"]

    gate.set()


def test_enqueue_launches_up_to_parallel_limit(client):
    import api.main as main

    gate = threading.Event()
    _install_gated_graph(client, gate, max_parallel=2)

    body = client.post(
        "/api/queue",
        json={"tickers": ["NVDA", "AAPL", "TSLA"], "trade_date": "2024-05-10"},
    ).json()
    assert len(body["running_run_ids"]) == 2

    state = main.get_store().list_queue()
    assert [r.ticker for r in state.running] == ["NVDA", "AAPL"]
    assert [p.ticker for p in state.pending] == ["TSLA"]

    gate.set()


def test_get_queue(client):
    gate = threading.Event()
    _install_gated_graph(client, gate)
    client.post("/api/queue", json={"tickers": ["NVDA", "AAPL"], "trade_date": "2024-05-10"})

    resp = client.get("/api/queue")
    assert resp.status_code == 200
    assert [r["ticker"] for r in resp.json()["running"]] == ["NVDA"]
    gate.set()


def test_parallelism_roundtrip(client):
    gate = threading.Event()
    _install_gated_graph(client, gate)

    assert client.get("/api/queue/parallelism").json()["max_parallel_runs"] == 1

    resp = client.put("/api/queue/parallelism", json={"max_parallel_runs": 3})
    assert resp.status_code == 200
    assert resp.json()["max_parallel_runs"] == 3
    assert client.get("/api/queue/parallelism").json()["max_parallel_runs"] == 3

    gate.set()


def test_parallelism_rejects_out_of_range(client):
    from api.schemas import MAX_PARALLEL_RUNS_LIMIT

    assert client.put("/api/queue/parallelism", json={"max_parallel_runs": 0}).status_code == 422
    resp = client.put(
        "/api/queue/parallelism", json={"max_parallel_runs": MAX_PARALLEL_RUNS_LIMIT + 1}
    )
    assert resp.status_code == 422


def test_raising_parallelism_launches_waiting_runs(client):
    import api.main as main

    gate = threading.Event()
    _install_gated_graph(client, gate)
    client.post(
        "/api/queue", json={"tickers": ["NVDA", "AAPL", "TSLA"], "trade_date": "2024-05-10"}
    )
    assert len(main.get_store().list_queue().running) == 1

    resp = client.put("/api/queue/parallelism", json={"max_parallel_runs": 3})
    assert resp.status_code == 200

    state = main.get_store().list_queue()
    assert [r.ticker for r in state.running] == ["NVDA", "AAPL", "TSLA"]
    assert state.pending == []

    gate.set()


def test_delete_pending_item(client):
    import api.main as main

    gate = threading.Event()
    _install_gated_graph(client, gate)
    body = client.post(
        "/api/queue", json={"tickers": ["NVDA", "AAPL", "TSLA"], "trade_date": "2024-05-10"}
    ).json()
    pending_id = body["run_ids"][1]  # AAPL

    resp = client.delete(f"/api/queue/{pending_id}")
    assert resp.status_code == 204
    assert pending_id not in {p.run_id for p in main.get_store().list_queue().pending}
    gate.set()


def test_delete_running_item_returns_409(client):
    gate = threading.Event()
    _install_gated_graph(client, gate)
    body = client.post(
        "/api/queue", json={"tickers": ["NVDA", "AAPL"], "trade_date": "2024-05-10"}
    ).json()
    running_id = body["running_run_ids"][0]

    resp = client.delete(f"/api/queue/{running_id}")
    assert resp.status_code == 409
    gate.set()


def test_clear_queue_keeps_running(client):
    import api.main as main

    gate = threading.Event()
    _install_gated_graph(client, gate)
    client.post(
        "/api/queue", json={"tickers": ["NVDA", "AAPL", "TSLA"], "trade_date": "2024-05-10"}
    )

    resp = client.delete("/api/queue")
    assert resp.status_code == 200
    assert resp.json()["removed"] == 2
    assert main.get_store().list_queue().pending == []
    assert main.get_store().list_queue().running != []
    gate.set()


def test_reorder_queue(client):
    gate = threading.Event()
    _install_gated_graph(client, gate)
    body = client.post(
        "/api/queue", json={"tickers": ["NVDA", "AAPL", "TSLA"], "trade_date": "2024-05-10"}
    ).json()
    a, b, c = body["run_ids"]  # NVDA(running), AAPL, TSLA

    resp = client.patch("/api/queue/order", json={"ordered_run_ids": [c, b]})
    assert resp.status_code == 200
    assert [p["run_id"] for p in resp.json()["pending"]] == [c, b]
    gate.set()
