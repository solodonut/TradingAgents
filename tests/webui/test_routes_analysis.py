def _install_fake_graph(client, chunks, decision, final_state):
    import api.main as main

    class _FakeGraph:
        def __init__(self, *a, **k):
            class _Inner:
                def stream(inner_self, init_state, **kwargs):
                    yield from chunks

            self.graph = _Inner()

        def propagate_meta(self):
            return decision, final_state

    def factory(req):
        return _FakeGraph(), {}, decision, final_state

    main.app.state.graph_factory = factory


def test_post_analysis_returns_run_id_and_streams_done(client):
    _install_fake_graph(
        client,
        chunks=[{"market_report": "m"}, {"final_trade_decision": "**Rating**: Buy"}],
        decision="Buy",
        final_state={"final_trade_decision": "**Rating**: Buy", "market_report": "m"},
    )
    resp = client.post(
        "/api/analysis",
        json={"ticker": "NVDA", "trade_date": "2024-05-10"},
    )
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    with client.stream("GET", f"/api/analysis/{run_id}/stream") as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "event: report_section" in body
    assert "event: done" in body
    assert "Buy" in body


def test_post_analysis_while_running_enqueues_instead_of_409(client):
    import api.main as main

    # an already-running row makes the scheduler keep the new POST pending
    store = main.get_store()
    store.insert_run("busy", "NVDA", "2024-05-10", "stock", {})

    _install_fake_graph(client, chunks=[], decision="Hold", final_state={})
    resp = client.post(
        "/api/analysis", json={"ticker": "AAPL", "trade_date": "2024-05-10"}
    )
    assert resp.status_code == 200
    new_id = resp.json()["run_id"]
    assert store.get_status(new_id) == "pending"


def test_cancel_running_analysis_marks_cancelled(client):
    import api.main as main

    store = main.get_store()
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})

    resp = client.post("/api/analysis/r1/cancel")

    assert resp.status_code == 200
    assert resp.json() == {"run_id": "r1", "status": "cancelled"}
    assert store.get_run("r1").status == "cancelled"
    assert store.has_running_run() is False


def test_cancel_completed_analysis_returns_409(client):
    import api.main as main

    store = main.get_store()
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    store.complete_run("r1", decision="Hold", result={})

    resp = client.post("/api/analysis/r1/cancel")

    assert resp.status_code == 409


def test_analysis_status_returns_runtime_telemetry(client):
    import api.main as main
    from api.telemetry import RunTelemetry

    store = main.get_store()
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    telemetry = RunTelemetry("r1")
    telemetry.mark_llm_start(
        model="claude-test",
        prompt_preview="Research Manager prompt",
        prompt_chars=23,
    )
    main.app.state.telemetry["r1"] = telemetry
    main.app.state.queues["r1"] = object()

    resp = client.get("/api/analysis/r1/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["db_status"] == "running"
    assert body["process_alive"] is True
    assert body["llm_active"] is True
    assert body["last_llm_model"] == "claude-test"
    assert body["last_prompt_preview"] == "Research Manager prompt"


def test_analysis_status_falls_back_for_old_runs_without_telemetry(client):
    import api.main as main

    main.get_store().insert_run("r1", "NVDA", "2024-05-10", "stock", {})

    resp = client.get("/api/analysis/r1/status")

    assert resp.status_code == 200
    assert resp.json()["db_status"] == "running"
    assert resp.json()["llm_active"] is False


def test_report_download_returns_markdown(client):
    import api.main as main

    store = main.get_store()
    store.insert_run("r9", "NVDA", "2024-05-10", "stock", {})
    store.complete_run(
        "r9",
        decision="Buy",
        result={
            "market_report": "## Market\nUp",
            "final_trade_decision": "**Rating**: Buy",
        },
    )
    resp = client.get("/api/analysis/r9/report")
    assert resp.status_code == 200
    assert "## Market" in resp.text
    assert "Rating" in resp.text
