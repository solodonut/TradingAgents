"""One real spawn, end to end: pickle boundary + mp.Queue + cross-process store.

The other launcher tests use stubs; these two pay for actual child interpreters
so that a regression in what crosses the process boundary (unpicklable payload,
child that can't reach the DB, cancel event that never arrives) is caught.

The child cannot inherit monkeypatches — a spawned interpreter re-imports
everything — so the fake graph builder is installed *inside* the child, by name.
"""

import queue
import time
import types
from pathlib import Path

import pytest

from api.scheduler import ProcessLauncher
from api.store import Store

CONFIG = {"ticker": "NVDA", "trade_date": "2024-05-10", "asset_type": "stock"}


# --- child-side fakes (module level: spawn pickles them by qualified name) ---


class _FakeInner:
    def __init__(self, chunks):
        self._chunks = chunks

    def stream(self, init_state, **kwargs):
        yield from self._chunks


def _fake_factory(req, callbacks=None):
    return (
        types.SimpleNamespace(
            graph=_FakeInner([{"market_report": "m"}, {"final_trade_decision": "**Rating**: Buy"}]),
            config={"log_enabled": False},
        ),
        {"company_of_interest": req.ticker},
        None,
        None,
    )


class _NeverEndingInner:
    """Streams until the runner notices the cancel event (or 20s, as a backstop)."""

    def stream(self, init_state, **kwargs):
        yield {"market_report": "m"}
        deadline = time.time() + 20
        while time.time() < deadline:
            time.sleep(0.05)
            yield {}


def _slow_factory(req, callbacks=None):
    return (
        types.SimpleNamespace(graph=_NeverEndingInner(), config={"log_enabled": False}),
        {"company_of_interest": req.ticker},
        None,
        None,
    )


def _child_with_fake_factory(*, db_path, run_id, config, event_queue, cancel_event):
    """Replaces ``run_in_child`` as the spawn target; installs a fake builder first."""
    import api.main as main
    from api.run_worker import run_in_child

    main.real_graph_factory = _fake_factory
    run_in_child(
        db_path=db_path,
        run_id=run_id,
        config=config,
        event_queue=event_queue,
        cancel_event=cancel_event,
    )


def _child_with_slow_factory(*, db_path, run_id, config, event_queue, cancel_event):
    import api.main as main
    from api.run_worker import run_in_child

    main.real_graph_factory = _slow_factory
    run_in_child(
        db_path=db_path,
        run_id=run_id,
        config=config,
        event_queue=event_queue,
        cancel_event=cancel_event,
    )


# --- parent-side harness ---


class _FakeScheduler:
    def __init__(self, store):
        self._store = store
        self.advanced = 0

    def store(self):
        return self._store

    def advance(self):
        self.advanced += 1


def _harness(tmp_path):
    db = tmp_path / "spawn.db"
    store = Store(db)
    app = types.SimpleNamespace(
        state=types.SimpleNamespace(queues={}, cancellations={}, telemetry={})
    )
    sched = _FakeScheduler(store)
    return store, app, sched, ProcessLauncher(app, sched, db)


def _drain(q: queue.Queue, timeout=60.0):
    items = []
    while True:
        item = q.get(timeout=timeout)
        items.append(item)
        if item is None:
            return items


@pytest.mark.unit
def test_real_child_process_streams_events_and_writes_the_store(tmp_path, monkeypatch):
    monkeypatch.setattr("api.run_worker.run_in_child", _child_with_fake_factory)
    store, app, sched, launcher = _harness(tmp_path)
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", CONFIG)

    launcher.launch(types.SimpleNamespace(run_id="r1", config=CONFIG))
    items = _drain(app.state.queues["r1"])

    assert items[-1] is None
    assert items[-2]["event"] == "done"
    assert items[-2]["data"]["decision"] == "Buy"
    # written by the child, read back here: WAL lets both processes touch one DB
    assert store.get_status("r1") == "completed"
    assert store.get_run("r1").result["market_report"] == "m"
    # telemetry forwarded over the pipe and applied to the parent's instance
    snapshot = app.state.telemetry["r1"].snapshot(db_status="completed", process_alive=False)
    assert snapshot["last_report_section"] == "final_trade_decision"


@pytest.mark.unit
def test_cancelling_reaches_the_child_process(tmp_path, monkeypatch):
    monkeypatch.setattr("api.run_worker.run_in_child", _child_with_slow_factory)
    store, app, sched, launcher = _harness(tmp_path)
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", CONFIG)

    launcher.launch(types.SimpleNamespace(run_id="r1", config=CONFIG))
    local = app.state.queues["r1"]
    # wait until the child is actually streaming, then cancel it
    first = local.get(timeout=60)
    assert first is not None
    app.state.cancellations["r1"].set()

    items = [first, *_drain(local)]
    assert any(
        isinstance(i, dict) and i["event"] == "cancelled" for i in items if i is not None
    )
    assert store.get_status("r1") == "cancelled"
    # advance() runs in the bridge thread after it joins the child
    deadline = time.time() + 15
    while sched.advanced == 0 and time.time() < deadline:
        time.sleep(0.05)
    assert sched.advanced == 1


@pytest.mark.unit
def test_child_db_path_is_the_real_file(tmp_path, monkeypatch):
    """Guards the wiring bug where the child would open a different DB."""
    monkeypatch.setattr("api.run_worker.run_in_child", _child_with_fake_factory)
    store, app, sched, launcher = _harness(tmp_path)
    assert Path(launcher._db_path) == tmp_path / "spawn.db"
    assert store.get_setting("nothing") is None
