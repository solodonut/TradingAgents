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
