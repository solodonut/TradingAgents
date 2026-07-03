"""Serial queue scheduler: starts the next pending run when idle."""

import queue as queue_mod
import threading

from api.runner import AnalysisRunner
from api.schemas import AnalysisRequest
from api.telemetry import RunTelemetry


class QueueScheduler:
    """Starts pending runs one at a time. ``advance`` is the single entry point.

    Called after enqueue and from each runner thread's finally; a lock keeps two
    runs from starting at once. ``advance`` loops past runs that fail to launch
    (e.g. graph build error), marking them error and trying the next.
    """

    def __init__(self, app):
        self._app = app
        self._lock = threading.Lock()

    def _store(self):
        from api.main import get_store

        return get_store()

    def advance(self) -> str | None:
        with self._lock:
            store = self._store()
            if store.has_running_run():
                return None
            while True:
                nxt = store.next_pending()
                if nxt is None:
                    return None
                if not store.start_run(nxt.run_id):
                    continue  # lost a race; try the next pending
                try:
                    self._launch(nxt)
                    return nxt.run_id
                except Exception as exc:  # noqa: BLE001 - bad config/build: skip it
                    store.mark_error(nxt.run_id, f"failed to start: {exc}")
                    continue

    def _launch(self, run) -> None:
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
            store=self._store(),
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
                self.advance()

        threading.Thread(target=_target, daemon=True).start()
