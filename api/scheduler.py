"""Queue scheduler: keeps up to N runs in flight, each in its own child process."""

import logging
import multiprocessing as mp
import queue as queue_mod
import threading
from pathlib import Path

from api.runner import AnalysisRunner
from api.schemas import (
    DEFAULT_MAX_PARALLEL_RUNS,
    MAX_PARALLEL_RUNS_LIMIT,
    AnalysisRequest,
)
from api.telemetry import RunTelemetry

logger = logging.getLogger(__name__)

# app_settings key holding the user's parallel-run choice.
MAX_PARALLEL_SETTING = "max_parallel_runs"

# How long the bridge thread waits on the child's queue before checking liveness.
_BRIDGE_POLL_SECONDS = 1.0


def read_max_parallel(store) -> int:
    """Current parallel-run limit, clamped to the supported range."""
    raw = store.get_setting(MAX_PARALLEL_SETTING)
    try:
        value = int(raw) if raw is not None else DEFAULT_MAX_PARALLEL_RUNS
    except (TypeError, ValueError):
        value = DEFAULT_MAX_PARALLEL_RUNS
    return max(1, min(MAX_PARALLEL_RUNS_LIMIT, value))


class InlineLauncher:
    """Runs an analysis in a background thread of this process.

    This is the seam tests rely on (``app.state.graph_factory`` injection), and
    it is what the single-process code path always did. Safe only for one run at
    a time in production because of the module-level globals documented in
    ``api.run_worker``; the fake graphs used in tests touch none of them.
    """

    def __init__(self, app, scheduler):
        self._app = app
        self._scheduler = scheduler

    def launch(self, run) -> None:
        app = self._app
        req = AnalysisRequest(**run.config)

        telemetry = RunTelemetry(run.run_id)
        app.state.telemetry[run.run_id] = telemetry
        app.state.starting_telemetry = telemetry
        try:
            graph, init_state, decision, final_state = app.state.graph_factory(req)
        finally:
            app.state.starting_telemetry = None

        q: queue_mod.Queue = queue_mod.Queue()
        app.state.queues[run.run_id] = q
        cancel_event = threading.Event()
        app.state.cancellations[run.run_id] = cancel_event

        runner = AnalysisRunner(
            store=self._scheduler.store(),
            event_queue=q,
            cancel_event=cancel_event,
            telemetry=telemetry,
            config=getattr(graph, "config", None) or {},
        )

        def _target():
            try:
                runner.run(
                    run_id=run.run_id,
                    graph=graph,
                    init_state=init_state,
                    decision=decision,
                    final_state=final_state,
                )
            finally:
                self._scheduler.advance()

        threading.Thread(target=_target, daemon=True).start()


class ProcessCancelEvent:
    """threading.Event-shaped view over a multiprocessing.Event.

    Lets ``POST /api/analysis/{run_id}/cancel`` keep calling ``.set()`` on
    whatever sits in ``app.state.cancellations`` without knowing which launcher
    started the run.
    """

    def __init__(self, mp_event):
        self._event = mp_event

    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


class ProcessLauncher:
    """Runs an analysis in a spawned child process, bridging its events back.

    The child writes SSE events onto a ``multiprocessing.Queue``; a bridge thread
    here copies them into the ordinary ``app.state.queues[run_id]`` and applies
    forwarded telemetry to ``app.state.telemetry[run_id]``. Everything above
    (SSE stream, cancel, status) therefore works unchanged.
    """

    def __init__(self, app, scheduler, db_path: Path):
        self._app = app
        self._scheduler = scheduler
        self._db_path = str(db_path)
        # spawn: a fresh interpreter that inherits none of the module-level
        # globals that make in-process parallelism unsafe.
        self._ctx = mp.get_context("spawn")

    def launch(self, run) -> None:
        from api.run_worker import run_in_child

        app = self._app
        # Validate the stored config here so a bad request is marked error by the
        # scheduler instead of costing a process spawn.
        AnalysisRequest(**run.config)

        child_queue = self._ctx.Queue()
        mp_cancel = self._ctx.Event()

        local_queue: queue_mod.Queue = queue_mod.Queue()
        telemetry = RunTelemetry(run.run_id)
        app.state.queues[run.run_id] = local_queue
        app.state.telemetry[run.run_id] = telemetry
        app.state.cancellations[run.run_id] = ProcessCancelEvent(mp_cancel)

        process = self._ctx.Process(
            target=run_in_child,
            kwargs={
                "db_path": self._db_path,
                "run_id": run.run_id,
                "config": dict(run.config),
                "event_queue": child_queue,
                "cancel_event": mp_cancel,
            },
            daemon=True,
        )
        try:
            process.start()
        except Exception:
            # Leave no half-registered run behind for the SSE/status routes.
            app.state.queues.pop(run.run_id, None)
            app.state.telemetry.pop(run.run_id, None)
            app.state.cancellations.pop(run.run_id, None)
            raise

        threading.Thread(
            target=self._bridge,
            args=(run.run_id, process, child_queue, local_queue, telemetry),
            daemon=True,
        ).start()

    def _bridge(self, run_id, process, child_queue, local_queue, telemetry) -> None:
        from api.run_worker import TELEMETRY_EVENT, apply_telemetry

        try:
            while True:
                try:
                    item = child_queue.get(timeout=_BRIDGE_POLL_SECONDS)
                except queue_mod.Empty:
                    if process.is_alive():
                        continue
                    # Child died without sending its sentinel (crash, OOM, kill).
                    # Without this the SSE stream would hang forever and the
                    # queue would never advance.
                    self._handle_dead_child(run_id, process, local_queue)
                    return
                if item is None:
                    local_queue.put(None)
                    return
                if isinstance(item, dict) and item.get("event") == TELEMETRY_EVENT:
                    apply_telemetry(telemetry, item.get("data") or {})
                    continue
                local_queue.put(item)
        finally:
            process.join(timeout=10)
            self._scheduler.advance()

    def _handle_dead_child(self, run_id, process, local_queue) -> None:
        store = self._scheduler.store()
        if store.get_status(run_id) == "running":
            message = f"analysis process exited unexpectedly (code {process.exitcode})"
            logger.error("run %s: %s", run_id, message)
            store.mark_error(run_id, message)
            local_queue.put({"event": "error", "data": {"message": message}})
        local_queue.put(None)


class QueueScheduler:
    """Keeps up to ``max_parallel_runs`` runs in flight. ``advance`` is the only entry point.

    Called after enqueue and when a run finishes; a lock keeps two callers from
    starting the same run. ``advance`` skips runs that fail to launch (e.g. a bad
    config), marking them error and trying the next.
    """

    def __init__(self, app):
        self._app = app
        self._lock = threading.Lock()
        self._inline = InlineLauncher(app, self)

    def store(self):
        from api.main import get_store

        return get_store()

    def _launcher(self):
        from api.main import real_graph_factory

        launcher = getattr(self._app.state, "run_launcher", None)
        if launcher is None:
            return self._inline
        # A test that injected its own graph_factory wants the run executed here,
        # against that fake graph (the documented seam) — a child process would
        # re-import the real factory. Decided per launch, not at startup, because
        # tests inject after the app has started.
        if getattr(self._app.state, "graph_factory", None) is not real_graph_factory:
            return self._inline
        return launcher

    def advance(self) -> str | None:
        with self._lock:
            store = self.store()
            clearer = getattr(self._app.state, "startup_cache_clearer", None)
            if clearer is not None and not clearer.is_ready():
                return None
            limit = read_max_parallel(store)
            launcher = self._launcher()
            first_started: str | None = None
            while store.running_count() < limit:
                nxt = store.next_pending()
                if nxt is None:
                    break
                if not store.start_run(nxt.run_id):
                    continue  # lost a race; try the next pending
                try:
                    launcher.launch(nxt)
                except Exception as exc:  # noqa: BLE001 - bad config/build: skip it
                    store.mark_error(nxt.run_id, f"failed to start: {exc}")
                    continue
                if first_started is None:
                    first_started = nxt.run_id
            return first_started
