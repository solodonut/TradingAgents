"""Child-process entry point for a single analysis run.

Runs are executed in separate processes (spawn) because three module-level
globals make in-process parallelism unsafe:

* ``dataflows.config._config`` — one dict, last ``set_config()`` wins globally.
* ``dataflows.config._PREFETCH_CTX`` — one slot; and ``AnalysisRunner.run``'s
  ``finally`` clears it unconditionally, which would blank a sibling run's context.
* ``akshare_utils.no_proxy_session()`` — pops proxy env vars and monkey-patches
  ``requests.Session.__init__``, restoring on exit. Interleaved entry/exit leaks
  the patch permanently and loses the proxy env vars for the whole process.

A spawned interpreter inherits none of them, so each run gets a clean slate.
Events travel back to the parent over a ``multiprocessing.Queue``; see
``api.scheduler.ProcessLauncher`` for the bridge that feeds them into the
existing ``app.state.queues`` / ``app.state.telemetry`` containers.
"""

from __future__ import annotations

import contextlib
import traceback
from pathlib import Path
from typing import Any

from api.telemetry import RunTelemetry

# Event name for telemetry updates tunnelled through the run's event queue.
TELEMETRY_EVENT = "__telemetry"

# Only these RunTelemetry methods may be applied by the parent bridge.
TELEMETRY_METHODS = frozenset(
    {"mark_llm_start", "mark_llm_end", "mark_llm_error", "mark_report"}
)


class ForwardingTelemetry(RunTelemetry):
    """RunTelemetry that also mirrors each update onto the event queue.

    Keeps a full local copy so ``callback_handler()`` behaves exactly as in the
    single-process path; the parent applies the same calls to its own instance so
    ``GET /api/analysis/{run_id}/status`` needs no changes.
    """

    def __init__(self, run_id: str, event_queue: Any):
        super().__init__(run_id)
        self._event_queue = event_queue

    def _forward(self, method: str, **kwargs: Any) -> None:
        # Telemetry must never break a run.
        with contextlib.suppress(Exception):
            self._event_queue.put(
                {"event": TELEMETRY_EVENT, "data": {"method": method, "kwargs": kwargs}}
            )

    def mark_llm_start(self, *, model, prompt_preview, prompt_chars) -> None:
        super().mark_llm_start(
            model=model, prompt_preview=prompt_preview, prompt_chars=prompt_chars
        )
        self._forward(
            "mark_llm_start",
            model=model,
            prompt_preview=prompt_preview,
            prompt_chars=prompt_chars,
        )

    def mark_llm_end(self) -> None:
        super().mark_llm_end()
        self._forward("mark_llm_end")

    def mark_llm_error(self, error: BaseException) -> None:
        super().mark_llm_error(error)
        self._forward("mark_llm_error", error=str(error))

    def mark_report(self, section: str) -> None:
        super().mark_report(section)
        self._forward("mark_report", section=section)


def apply_telemetry(telemetry: RunTelemetry, payload: dict) -> None:
    """Apply one forwarded telemetry update to the parent's RunTelemetry."""
    method = payload.get("method")
    if method not in TELEMETRY_METHODS:
        return
    kwargs = dict(payload.get("kwargs") or {})
    if method == "mark_llm_error":
        # BaseException does not survive pickling reliably; RunTelemetry only
        # ever calls str() on it, so a plain RuntimeError round-trips exactly.
        telemetry.mark_llm_error(RuntimeError(kwargs.get("error", "")))
        return
    getattr(telemetry, method)(**kwargs)


def run_in_child(
    *,
    db_path: str,
    run_id: str,
    config: dict,
    event_queue: Any,
    cancel_event: Any,
) -> None:
    """Build the graph and stream one run, entirely inside this process.

    ``config`` is the stored ``AnalysisRequest`` payload. Always terminates the
    event stream with a ``None`` sentinel so the parent bridge can finish.
    """
    from api.main import real_graph_factory
    from api.runner import AnalysisRunner
    from api.schemas import AnalysisRequest
    from api.store import Store

    store = Store(Path(db_path))
    telemetry = ForwardingTelemetry(run_id, event_queue)
    try:
        req = AnalysisRequest(**config)
        graph, init_state, decision, final_state = real_graph_factory(
            req, callbacks=[telemetry.callback_handler()]
        )
    except Exception as exc:  # noqa: BLE001 - bad config / graph build failure
        traceback.print_exc()
        store.mark_error(run_id, f"failed to start: {exc}")
        event_queue.put({"event": "error", "data": {"message": f"failed to start: {exc}"}})
        event_queue.put(None)
        return

    runner = AnalysisRunner(
        store=store,
        event_queue=event_queue,
        cancel_event=cancel_event,
        telemetry=telemetry,
        config=getattr(graph, "config", None) or {},
    )
    # AnalysisRunner.run() already emits `error` on failure and puts the None
    # sentinel in its finally, so no extra wrapping is needed here.
    runner.run(
        run_id=run_id,
        graph=graph,
        init_state=init_state,
        decision=decision,
        final_state=final_state,
    )
