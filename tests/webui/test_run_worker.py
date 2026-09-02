"""Child-process entry point, exercised in-process (no real spawn).

``run_in_child`` is what a spawned worker executes; running it here directly
proves the store writes, the event order and the telemetry forwarding are right
without paying for an interpreter start.
"""

import queue
import threading
import types

import pytest

from api.run_worker import (
    TELEMETRY_EVENT,
    ForwardingTelemetry,
    apply_telemetry,
    run_in_child,
)
from api.store import Store
from api.telemetry import RunTelemetry

CONFIG = {"ticker": "NVDA", "trade_date": "2024-05-10", "asset_type": "stock"}


def _drain(q: queue.Queue) -> list:
    """Everything the run pushed, up to and including the None sentinel."""
    items = []
    while True:
        item = q.get(timeout=5)
        items.append(item)
        if item is None:
            return items


def _fake_factory(chunks):
    def factory(req, callbacks=None):
        class _Inner:
            def stream(inner_self, init_state, **kwargs):
                yield from chunks

        # log_enabled off: keeps the event stream to the SSE events under test
        # (and off the real ~/.tradingagents log dir).
        graph = types.SimpleNamespace(graph=_Inner(), config={"log_enabled": False})
        return graph, {"company_of_interest": req.ticker}, None, None

    return factory


@pytest.mark.unit
def test_run_in_child_completes_run_and_emits_events(tmp_path, monkeypatch):
    import api.main as main

    db = tmp_path / "worker.db"
    store = Store(db)
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", CONFIG)
    monkeypatch.setattr(
        main,
        "real_graph_factory",
        _fake_factory([{"market_report": "m"}, {"final_trade_decision": "**Rating**: Buy"}]),
    )

    q: queue.Queue = queue.Queue()
    run_in_child(
        db_path=str(db),
        run_id="r1",
        config=CONFIG,
        event_queue=q,
        cancel_event=threading.Event(),
    )

    items = _drain(q)
    assert items[-1] is None
    assert items[-2]["event"] == "done"
    assert items[-2]["data"]["decision"] == "Buy"

    sections = [
        i["data"]["section"] for i in items[:-1] if i["event"] == "report_section"
    ]
    assert sections == ["market_report", "final_trade_decision"]

    run = store.get_run("r1")
    assert run.status == "completed"
    assert run.result["market_report"] == "m"


@pytest.mark.unit
def test_run_in_child_forwards_telemetry_for_each_report(tmp_path, monkeypatch):
    import api.main as main

    db = tmp_path / "worker.db"
    store = Store(db)
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", CONFIG)
    monkeypatch.setattr(
        main, "real_graph_factory", _fake_factory([{"market_report": "m"}])
    )

    q: queue.Queue = queue.Queue()
    run_in_child(
        db_path=str(db),
        run_id="r1",
        config=CONFIG,
        event_queue=q,
        cancel_event=threading.Event(),
    )

    forwarded = [
        i["data"]
        for i in _drain(q)
        if isinstance(i, dict) and i.get("event") == TELEMETRY_EVENT
    ]
    assert {"method": "mark_report", "kwargs": {"section": "market_report"}} in forwarded


@pytest.mark.unit
def test_run_in_child_cancels_mid_stream(tmp_path, monkeypatch):
    import api.main as main

    db = tmp_path / "worker.db"
    store = Store(db)
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", CONFIG)
    monkeypatch.setattr(
        main, "real_graph_factory", _fake_factory([{"market_report": "m"}])
    )

    cancel = threading.Event()
    cancel.set()
    q: queue.Queue = queue.Queue()
    run_in_child(
        db_path=str(db),
        run_id="r1",
        config=CONFIG,
        event_queue=q,
        cancel_event=cancel,
    )

    items = _drain(q)
    assert items[-1] is None
    assert any(i["event"] == "cancelled" for i in items[:-1] if isinstance(i, dict))
    assert store.get_status("r1") == "cancelled"


@pytest.mark.unit
def test_run_in_child_marks_error_when_graph_build_fails(tmp_path, monkeypatch):
    """A build failure must still terminate the stream, or the parent bridge hangs."""
    import api.main as main

    db = tmp_path / "worker.db"
    store = Store(db)
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", CONFIG)

    def boom(req, callbacks=None):
        raise RuntimeError("build failed")

    monkeypatch.setattr(main, "real_graph_factory", boom)

    q: queue.Queue = queue.Queue()
    run_in_child(
        db_path=str(db),
        run_id="r1",
        config=CONFIG,
        event_queue=q,
        cancel_event=threading.Event(),
    )

    items = _drain(q)
    assert items[-1] is None
    assert items[0]["event"] == "error"
    assert "build failed" in items[0]["data"]["message"]
    assert store.get_status("r1") == "error"


@pytest.mark.unit
def test_run_in_child_marks_error_for_invalid_config(tmp_path):
    db = tmp_path / "worker.db"
    store = Store(db)
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})

    q: queue.Queue = queue.Queue()
    run_in_child(
        db_path=str(db),
        run_id="r1",
        config={"ticker": "NVDA"},  # missing trade_date
        event_queue=q,
        cancel_event=threading.Event(),
    )

    items = _drain(q)
    assert items[0]["event"] == "error"
    assert store.get_status("r1") == "error"


@pytest.mark.unit
def test_forwarding_telemetry_mirrors_llm_calls_onto_the_queue():
    q: queue.Queue = queue.Queue()
    telemetry = ForwardingTelemetry("r1", q)

    telemetry.mark_llm_start(model="m", prompt_preview="p", prompt_chars=1)
    telemetry.mark_llm_end()
    telemetry.mark_llm_error(RuntimeError("nope"))

    methods = [q.get_nowait()["data"]["method"] for _ in range(3)]
    assert methods == ["mark_llm_start", "mark_llm_end", "mark_llm_error"]
    # local copy stays complete, so callback_handler() behaves as single-process
    snapshot = telemetry.snapshot(db_status="running", process_alive=True)
    assert snapshot["last_llm_model"] == "m"
    assert snapshot["last_llm_error"] == "nope"


@pytest.mark.unit
def test_apply_telemetry_replays_on_the_parent_instance():
    q: queue.Queue = queue.Queue()
    child = ForwardingTelemetry("r1", q)
    parent = RunTelemetry("r1")

    child.mark_llm_start(model="m", prompt_preview="p", prompt_chars=7)
    child.mark_llm_error(RuntimeError("boom"))
    child.mark_report("market_report")

    while not q.empty():
        apply_telemetry(parent, q.get_nowait()["data"])

    snapshot = parent.snapshot(db_status="running", process_alive=True)
    assert snapshot["last_llm_model"] == "m"
    assert snapshot["last_prompt_chars"] == 7
    assert snapshot["last_llm_error"] == "boom"
    assert snapshot["last_report_section"] == "market_report"


@pytest.mark.unit
def test_apply_telemetry_ignores_unknown_methods():
    parent = RunTelemetry("r1")
    apply_telemetry(parent, {"method": "snapshot", "kwargs": {}})
    apply_telemetry(parent, {"method": "__init__", "kwargs": {"run_id": "hacked"}})
    assert parent.snapshot(db_status=None, process_alive=False)["run_id"] == "r1"
