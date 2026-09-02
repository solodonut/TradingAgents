"""ProcessLauncher's parent side: the event bridge and the dead-child fallback.

No real process is spawned here — a stub multiprocessing context and a plain
``queue.Queue`` stand in, because ``mp.Queue``/``mp.Event`` are duck-compatible
with them for everything the bridge touches.
"""

import queue
import threading
import types

import pytest
from pydantic import ValidationError

from api.run_worker import TELEMETRY_EVENT
from api.scheduler import ProcessCancelEvent, ProcessLauncher
from api.store import Store
from api.telemetry import RunTelemetry

CONFIG = {"ticker": "NVDA", "trade_date": "2024-05-10", "asset_type": "stock"}


class _FakeProcess:
    def __init__(self, alive=True, exitcode=None):
        self._alive = alive
        self.exitcode = exitcode
        self.joined = False
        self.started = False

    def start(self):
        self.started = True

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        self.joined = True


class _FakeScheduler:
    def __init__(self, store):
        self._store = store
        self.advanced = 0

    def store(self):
        return self._store

    def advance(self):
        self.advanced += 1


def _app():
    return types.SimpleNamespace(
        state=types.SimpleNamespace(queues={}, cancellations={}, telemetry={})
    )


@pytest.fixture()
def env(tmp_path):
    store = Store(tmp_path / "launcher.db")
    app = _app()
    sched = _FakeScheduler(store)
    launcher = ProcessLauncher(app, sched, tmp_path / "launcher.db")
    return types.SimpleNamespace(store=store, app=app, sched=sched, launcher=launcher)


@pytest.mark.unit
def test_bridge_copies_events_and_terminates_on_sentinel(env):
    child_q: queue.Queue = queue.Queue()
    local_q: queue.Queue = queue.Queue()
    telemetry = RunTelemetry("r1")
    child_q.put({"event": "report_section", "data": {"section": "market_report"}})
    child_q.put({"event": "done", "data": {"decision": "Buy"}})
    child_q.put(None)
    process = _FakeProcess()

    env.launcher._bridge("r1", process, child_q, local_q, telemetry)

    assert local_q.get_nowait()["event"] == "report_section"
    assert local_q.get_nowait()["event"] == "done"
    assert local_q.get_nowait() is None
    assert process.joined is True
    assert env.sched.advanced == 1


@pytest.mark.unit
def test_bridge_applies_telemetry_without_forwarding_it(env):
    """__telemetry is an internal channel: it updates state, it is not an SSE event."""
    child_q: queue.Queue = queue.Queue()
    local_q: queue.Queue = queue.Queue()
    telemetry = RunTelemetry("r1")
    child_q.put(
        {
            "event": TELEMETRY_EVENT,
            "data": {
                "method": "mark_llm_start",
                "kwargs": {"model": "m", "prompt_preview": "p", "prompt_chars": 3},
            },
        }
    )
    child_q.put(None)

    env.launcher._bridge("r1", _FakeProcess(), child_q, local_q, telemetry)

    assert local_q.get_nowait() is None
    assert local_q.empty()
    snapshot = telemetry.snapshot(db_status="running", process_alive=True)
    assert snapshot["last_llm_model"] == "m"
    assert snapshot["llm_active"] is True


@pytest.mark.unit
def test_bridge_marks_error_when_child_dies_without_sentinel(env, monkeypatch):
    """OOM/kill: without this the SSE stream hangs and the queue never advances."""
    monkeypatch.setattr("api.scheduler._BRIDGE_POLL_SECONDS", 0.01)
    env.store.insert_run("r1", "NVDA", "2024-05-10", "stock", CONFIG)
    local_q: queue.Queue = queue.Queue()

    env.launcher._bridge(
        "r1", _FakeProcess(alive=False, exitcode=-9), queue.Queue(), local_q, RunTelemetry("r1")
    )

    event = local_q.get_nowait()
    assert event["event"] == "error"
    assert "-9" in event["data"]["message"]
    assert local_q.get_nowait() is None
    assert env.store.get_status("r1") == "error"
    assert env.sched.advanced == 1


@pytest.mark.unit
def test_bridge_does_not_error_a_run_that_already_finished(env, monkeypatch):
    """Child exited right after completing: only close the stream."""
    monkeypatch.setattr("api.scheduler._BRIDGE_POLL_SECONDS", 0.01)
    env.store.insert_run("r1", "NVDA", "2024-05-10", "stock", CONFIG)
    env.store.complete_run("r1", decision="Buy", result={})
    local_q: queue.Queue = queue.Queue()

    env.launcher._bridge(
        "r1", _FakeProcess(alive=False, exitcode=0), queue.Queue(), local_q, RunTelemetry("r1")
    )

    assert local_q.get_nowait() is None
    assert env.store.get_status("r1") == "completed"


@pytest.mark.unit
def test_launch_registers_state_and_starts_the_child(env, monkeypatch):
    created = {}

    class _Ctx:
        def Queue(self):
            created["queue"] = queue.Queue()
            return created["queue"]

        def Event(self):
            created["event"] = threading.Event()
            return created["event"]

        def Process(self, target, kwargs, daemon):
            created["process"] = _FakeProcess()
            created["target"] = target
            created["kwargs"] = kwargs
            return created["process"]

    monkeypatch.setattr(env.launcher, "_ctx", _Ctx())
    run = types.SimpleNamespace(run_id="r1", config=CONFIG)

    env.launcher.launch(run)

    assert created["process"].started is True
    assert created["kwargs"]["run_id"] == "r1"
    assert created["kwargs"]["db_path"] == str(env.launcher._db_path)
    assert env.app.state.queues["r1"] is not created["queue"]  # parent-side queue
    assert isinstance(env.app.state.telemetry["r1"], RunTelemetry)
    assert isinstance(env.app.state.cancellations["r1"], ProcessCancelEvent)

    # cancelling the run must set the child's event
    env.app.state.cancellations["r1"].set()
    assert created["event"].is_set() is True

    created["queue"].put(None)  # let the bridge thread finish
    assert _wait_until(lambda: env.sched.advanced == 1)


@pytest.mark.unit
def test_launch_rejects_bad_config_before_spawning(env, monkeypatch):
    class _Boom:
        def Queue(self):
            raise AssertionError("must not reach the spawn")

    monkeypatch.setattr(env.launcher, "_ctx", _Boom())
    run = types.SimpleNamespace(run_id="r1", config={"ticker": "NVDA"})

    with pytest.raises(ValidationError):
        env.launcher.launch(run)

    assert env.app.state.queues == {}
    assert env.app.state.cancellations == {}


@pytest.mark.unit
def test_launch_cleans_up_when_the_process_fails_to_start(env, monkeypatch):
    """A half-registered run would leave the SSE/status routes waiting forever."""

    class _Ctx:
        def Queue(self):
            return queue.Queue()

        def Event(self):
            return threading.Event()

        def Process(self, target, kwargs, daemon):
            class _Dead(_FakeProcess):
                def start(self):
                    raise OSError("cannot fork")

            return _Dead()

    monkeypatch.setattr(env.launcher, "_ctx", _Ctx())

    with pytest.raises(OSError):
        env.launcher.launch(types.SimpleNamespace(run_id="r1", config=CONFIG))

    assert env.app.state.queues == {}
    assert env.app.state.telemetry == {}
    assert env.app.state.cancellations == {}


@pytest.mark.unit
def test_process_cancel_event_delegates():
    mp_event = threading.Event()
    adapter = ProcessCancelEvent(mp_event)
    assert adapter.is_set() is False
    adapter.set()
    assert mp_event.is_set() is True
    assert adapter.is_set() is True


def _wait_until(predicate, timeout=2.0):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False
