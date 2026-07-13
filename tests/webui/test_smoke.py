import pytest
from fastapi.testclient import TestClient


@pytest.mark.smoke
def test_app_imports_and_has_routes():
    from api.main import app

    client = TestClient(app)
    assert client.get("/api/config/options").status_code == 200
    assert client.get("/api/history").status_code == 200
    assert client.get("/api/analysis").status_code == 405


@pytest.mark.smoke
def test_chat_routes_registered():
    from api.main import app

    client = TestClient(app)
    # POST /api/chat/sessions does not call the chat_llm_factory (run_id is
    # optional), so an empty body returns 200 — never 404 — when the chat
    # router is registered.
    assert client.post("/api/chat/sessions", json={}).status_code != 404


@pytest.mark.smoke
def test_queue_routes_registered():
    from api.main import app

    client = TestClient(app)
    assert client.get("/api/queue").status_code == 200


@pytest.mark.smoke
def test_snapshot_routes_registered():
    from api.main import app

    client = TestClient(app)
    assert client.get("/api/etf/510300.SS/dates").status_code == 200


@pytest.mark.smoke
def test_diagnostics_route_registered_and_streams():
    from dataclasses import dataclass

    from api.main import app

    @dataclass
    class _Cell:
        method: str
        vendor: str
        group: str
        status: str
        elapsed_ms: float
        raw: str
        error_type: str | None

    def fake_iter(code, ref_date):
        yield _Cell("get_etf_profile", "tushare", "ETF 核心", "ok", 1.0, "hi", None)
        yield _Cell("get_etf_profile", "akshare", "ETF 核心", "no_perm", 2.0, "积分不足", None)

    app.state.diagnostics_probe_iter = fake_iter
    app.state.diagnostics_count = lambda: 2
    try:
        client = TestClient(app)
        r = client.get("/api/diagnostics/etf/510300.SS?ref_date=2026-07-13")
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        body = r.text
        assert "event: start" in body
        assert body.count("event: cell") == 2
        assert "event: done" in body
        assert "no_perm" in body
    finally:
        app.state.diagnostics_probe_iter = None
        app.state.diagnostics_count = None
