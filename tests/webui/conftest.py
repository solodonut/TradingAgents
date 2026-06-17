import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with an isolated temp DB and no real graph."""
    import api.main as main

    monkeypatch.setattr(main, "DB_PATH", tmp_path / "webui.db")
    main.app.state.store = None  # force re-init against temp DB
    main.app.state.queues = {}
    main.app.state.cancellations = {}
    main.app.state.telemetry = {}
    main.app.state.starting_telemetry = None
    with TestClient(main.app) as c:
        yield c
