"""Bridges TradingAgentsGraph.stream() to SSE events via a background thread."""

import queue
import threading
import time
import traceback

from api.store import Store
from api.telemetry import RunTelemetry

# section field name -> (agent name, team)
REPORT_SECTIONS: dict[str, tuple[str, str]] = {
    "market_report": ("market_analyst", "analyst"),
    "sentiment_report": ("social_analyst", "analyst"),
    "news_report": ("news_analyst", "analyst"),
    "fundamentals_report": ("fundamentals_analyst", "analyst"),
    "investment_plan": ("research_manager", "research"),
    "trader_investment_plan": ("trader", "trading"),
    "final_trade_decision": ("portfolio_manager", "portfolio"),
}

REPORT_SECTION_KEYS = frozenset(REPORT_SECTIONS)


def chunk_to_events(chunk: dict, seen: set[str]) -> list[dict]:
    """Translate one LangGraph stream chunk into SSE event dicts.

    Each event dict has shape {"event": <type>, "data": <payload>}.
    Mutates ``seen`` to track which report sections were already emitted.
    """
    events: list[dict] = []
    for section, (agent, team) in REPORT_SECTIONS.items():
        content = chunk.get(section)
        if not content or section in seen:
            continue
        seen.add(section)
        events.append(
            {"event": "agent_status", "data": {"agent": agent, "team": team, "status": "done"}}
        )
        events.append(
            {
                "event": "report_section",
                "data": {"section": section, "content": content},
            }
        )
        events.append(
            {
                "event": "message",
                "data": {"agent": agent, "team": team, "content": content, "ts": int(time.time())},
            }
        )
    return events


class AnalysisRunner:
    """Runs a graph stream synchronously, pushing SSE events onto a queue.

    Designed to be invoked inside a background thread. ``decision`` and
    ``final_state`` are precomputed by the caller (the route handler), because
    TradingAgentsGraph stores them on the instance after ``propagate``; here we
    accept them explicitly so the runner stays testable with a fake graph.
    """

    def __init__(
        self,
        store: Store,
        event_queue: "queue.Queue",
        cancel_event: threading.Event | None = None,
        telemetry: RunTelemetry | None = None,
    ):
        self._store = store
        self._q = event_queue
        self._cancel_event = cancel_event
        self._telemetry = telemetry

    def run(self, run_id, graph, init_state, decision, final_state) -> None:
        seen: set[str] = set()
        accumulated: dict = {}
        stream_args = getattr(graph, "_stream_args", {}) or {}
        try:
            for chunk in graph.graph.stream(init_state, **stream_args):
                if self._is_cancelled():
                    self._emit_cancelled(run_id)
                    return
                if isinstance(chunk, dict):
                    accumulated.update(chunk)
                    partial = {
                        key: value
                        for key, value in chunk.items()
                        if key in REPORT_SECTION_KEYS and value
                    }
                    if partial:
                        self._store.update_partial_result(run_id, partial)
                        if self._telemetry is not None:
                            for section in partial:
                                self._telemetry.mark_report(section)
                for event in chunk_to_events(chunk, seen):
                    self._q.put(event)
                if self._is_cancelled():
                    self._emit_cancelled(run_id)
                    return

            if final_state is None:
                final_state = accumulated
            if decision is None:
                decision = _extract_decision(graph, final_state)

            self._store.complete_run(
                run_id, decision=decision or "Hold", result=final_state or {}
            )
            self._q.put(
                {
                    "event": "done",
                    "data": {
                        "decision": decision or "Hold",
                        "final_trade_decision": (final_state or {}).get(
                            "final_trade_decision", ""
                        ),
                        "run_id": run_id,
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._store.mark_error(run_id, str(exc))
            self._q.put({"event": "error", "data": {"message": str(exc)}})
        finally:
            self._q.put(None)

    def _is_cancelled(self) -> bool:
        return bool(self._cancel_event and self._cancel_event.is_set())

    def _emit_cancelled(self, run_id: str) -> None:
        self._store.cancel_run(run_id)
        self._q.put(
            {
                "event": "cancelled",
                "data": {"run_id": run_id, "message": "analysis cancelled"},
            }
        )


def _extract_decision(graph, final_state: dict) -> str | None:
    """Best-effort: derive the 5-tier decision from final_trade_decision prose."""
    text = (final_state or {}).get("final_trade_decision", "")
    if not text:
        return None
    processor = getattr(graph, "process_signal", None)
    if callable(processor):
        try:
            return processor(text)
        except Exception:  # noqa: BLE001
            pass
    try:
        from tradingagents.agents.utils.rating import parse_rating

        return parse_rating(text)
    except Exception:  # noqa: BLE001
        return None
