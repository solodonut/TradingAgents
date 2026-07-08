import time

import pytest
from fastapi.testclient import TestClient
from sse_starlette.sse import AppStatus


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with an isolated temp DB and no real graph."""
    import api.main as main

    monkeypatch.setattr(main, "DB_PATH", tmp_path / "webui.db")
    main.app.state.store = None  # force re-init against temp DB
    main.app.state.startup_cache_clearer = None
    main.DEFAULT_CONFIG["data_cache_dir"] = str(tmp_path / "cache")
    main.app.state.queues = {}
    main.app.state.cancellations = {}
    main.app.state.telemetry = {}
    main.app.state.starting_telemetry = None
    main.app.state.scheduler = None  # re-created by startup against fresh state
    main.app.state.chat_llm_factory = None
    AppStatus.should_exit = False
    AppStatus.should_exit_event = None
    with TestClient(main.app) as c:
        yield c
        AppStatus.should_exit = False
        AppStatus.should_exit_event = None
        # Drain in-flight scheduler threads before the next test resets app.state.
        # Queue tests launch real daemon runner threads via a gated fake graph; once
        # the test releases its gate the run completes and its finally-block calls
        # scheduler.advance() against the global store. If we don't wait here, that
        # thread can mutate the NEXT test's freshly-reset app.state/DB and flake it.
        store = main.app.state.store
        if store is not None:
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if not store.has_running_run() and not store.list_queue().pending:
                    break
                time.sleep(0.02)
