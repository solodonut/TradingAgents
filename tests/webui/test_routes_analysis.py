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


def test_second_analysis_while_running_returns_409(client, monkeypatch):
    import api.main as main

    monkeypatch.setattr(main.get_store(), "has_running_run", lambda: True)
    resp = client.post(
        "/api/analysis", json={"ticker": "NVDA", "trade_date": "2024-05-10"}
    )
    assert resp.status_code == 409


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
