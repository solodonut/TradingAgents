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
    "validation_report": ("report_validator", "validation"),
}

REPORT_SECTION_KEYS = frozenset(REPORT_SECTIONS)

# Debate progress ---------------------------------------------------------
# speaker key -> (prose prefix, Chinese label)
INVEST_SPEAKERS: dict[str, tuple[str, str]] = {
    "bull": ("Bull Analyst:", "多方"),
    "bear": ("Bear Analyst:", "空方"),
}
RISK_SPEAKERS: dict[str, tuple[str, str]] = {
    "aggressive": ("Aggressive Analyst:", "激进"),
    "conservative": ("Conservative Analyst:", "保守"),
    "neutral": ("Neutral Analyst:", "中立"),
}
RISK_SPEAKER_ORDER: tuple[str, ...] = ("aggressive", "conservative", "neutral")
_SPEAKER_PREFIXES: tuple[str, ...] = tuple(
    prefix for prefix, _ in (*INVEST_SPEAKERS.values(), *RISK_SPEAKERS.values())
)


def _strip_speaker_prefix(text: str) -> str:
    """Drop a leading 'Xxx Analyst:' label from a debate argument."""
    stripped = text.lstrip()
    for prefix in _SPEAKER_PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return stripped


def _round_event(*, team, round_no, total, speaker, label, content) -> dict:
    return {
        "event": "debate_round",
        "data": {
            "team": team,
            "round": round_no,
            "total": total,
            "speaker": speaker,
            "speaker_label": label,
            "content": _strip_speaker_prefix(content or ""),
        },
    }


def debate_events(chunk: dict, tracker: dict, rounds_cfg: dict) -> list[dict]:
    """Emit `debate_round` events when a debate state's `count` advances.

    `chunk` is a full accumulated state (stream_mode='values'), so `count` is
    monotonic and grows by exactly one per debate turn. `tracker` remembers the
    last count already emitted per team; `rounds_cfg` carries the totals.
    """
    events: list[dict] = []

    invest = chunk.get("investment_debate_state")
    if isinstance(invest, dict):
        count = invest.get("count") or 0
        if count > tracker.get("invest_count", 0):
            tracker["invest_count"] = count
            speaker = "bull" if count % 2 == 1 else "bear"
            _, label = INVEST_SPEAKERS[speaker]
            events.append(
                _round_event(
                    team="invest",
                    round_no=(count + 1) // 2,
                    total=rounds_cfg.get("invest_total", 1),
                    speaker=speaker,
                    label=label,
                    content=invest.get("current_response", ""),
                )
            )

    risk = chunk.get("risk_debate_state")
    if isinstance(risk, dict):
        count = risk.get("count") or 0
        if count > tracker.get("risk_count", 0):
            tracker["risk_count"] = count
            speaker = RISK_SPEAKER_ORDER[(count - 1) % 3]
            _, label = RISK_SPEAKERS[speaker]
            events.append(
                _round_event(
                    team="risk",
                    round_no=(count + 2) // 3,
                    total=rounds_cfg.get("risk_total", 1),
                    speaker=speaker,
                    label=label,
                    content=risk.get(f"current_{speaker}_response", ""),
                )
            )

    return events


def _rounds_config(graph) -> dict:
    """Read debate round totals from graph.config, defaulting to 1."""
    config = getattr(graph, "config", None) or {}
    return {
        "invest_total": int(config.get("max_debate_rounds", 1) or 1),
        "risk_total": int(config.get("max_risk_discuss_rounds", 1) or 1),
    }


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
        debate_tracker: dict = {}
        rounds_cfg = _rounds_config(graph)
        accumulated: dict = {}
        stream_args = getattr(graph, "_stream_args", {}) or {}
        instrument_name = getattr(graph, "_instrument_name", None)
        if instrument_name:
            self._store.set_instrument_name(run_id, instrument_name)
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
                if isinstance(chunk, dict):
                    for event in debate_events(chunk, debate_tracker, rounds_cfg):
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
