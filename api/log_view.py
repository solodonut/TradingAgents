"""Build summarized timeline data from TradingAgents JSONL run logs."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ms_label(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f} ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rem = divmod(seconds, 60)
    return f"{int(minutes)}m {rem:.1f}s"


def _compact(value: Any, limit: int = 220) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _event_label(event: dict[str, Any]) -> str:
    event_type = event.get("event_type")
    if event_type in {"node_enter", "node_exit"}:
        return str(event.get("node", event_type))
    if event_type == "llm_call":
        return str(event.get("model", "llm_call"))
    if event_type == "vendor_call":
        method = event.get("method", "vendor_call")
        vendor = event.get("vendor", "")
        return f"{method} / {vendor}" if vendor else str(method)
    return str(event.get("node") or event.get("method") or event.get("event_type", "event"))


def _event_detail(event: dict[str, Any]) -> str:
    event_type = event.get("event_type")
    if event_type == "vendor_call":
        return _compact(event.get("args") or event.get("error") or event.get("message"))
    if event_type == "llm_call":
        return _compact(event.get("response"))
    if event_type == "error":
        return _compact(event.get("error") or event.get("message") or event.get("exception"))
    return _compact(
        {
            k: v
            for k, v in event.items()
            if k not in {"prompt", "response", "config", "ts", "run_id"}
        }
    )


def read_log_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event["_line"] = line_no
            events.append(event)
    return events


def _error_message(event: dict[str, Any]) -> str:
    for key in ("error", "message", "exception", "detail"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if event.get("ok") is False:
        return "operation failed"
    return ""


def _run_result_error(result: dict[str, Any] | None) -> str:
    if not result:
        return ""
    for key in ("error", "message", "reason"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def build_log_view(
    *,
    run_id: str,
    events: list[dict[str, Any]],
    run_result: dict[str, Any] | None,
) -> dict[str, Any]:
    dated = [(event, _parse_ts(event["ts"])) for event in events if isinstance(event.get("ts"), str)]
    if not dated:
        return {
            "run_id": run_id,
            "elapsed_ms": 0,
            "elapsed_label": "0 ms",
            "event_counts": dict(Counter(event.get("event_type", "unknown") for event in events)),
            "duration_totals": {},
            "timeline": [],
            "slow_events": [],
            "node_totals": [],
            "errors": _build_errors(events, run_result),
        }

    run_start = min(ts for _, ts in dated)
    run_end = max(ts for _, ts in dated)
    elapsed_ms = (run_end - run_start).total_seconds() * 1000
    totals = Counter()
    node_totals: defaultdict[str, float] = defaultdict(float)
    timeline: list[dict[str, Any]] = []

    for event, end_ts in dated:
        elapsed = event.get("elapsed_ms")
        if not isinstance(elapsed, (int, float)):
            continue
        duration_ms = max(float(elapsed), 0)
        start_ts = end_ts - timedelta(milliseconds=duration_ms)
        start_ms = max((start_ts - run_start).total_seconds() * 1000, 0)
        end_ms = max((end_ts - run_start).total_seconds() * 1000, 0)
        event_type = str(event.get("event_type", "unknown"))
        label = _event_label(event)
        totals[event_type] += duration_ms
        if event_type == "node_exit":
            node_totals[label] += duration_ms
        timeline.append(
            {
                "seq": event.get("seq"),
                "type": event_type,
                "label": label,
                "start_ms": round(start_ms, 3),
                "end_ms": round(end_ms, 3),
                "duration_ms": round(duration_ms, 3),
                "duration_label": _ms_label(duration_ms),
                "ts": event["ts"],
                "ok": event.get("ok"),
                "detail": _event_detail(event),
            }
        )

    slow_events = sorted(timeline, key=lambda item: item["duration_ms"], reverse=True)[:30]
    node_rows = [
        {"label": label, "duration_ms": round(ms, 3), "duration_label": _ms_label(ms)}
        for label, ms in sorted(node_totals.items(), key=lambda item: item[1], reverse=True)
    ]

    return {
        "run_id": run_id,
        "elapsed_ms": round(elapsed_ms, 3),
        "elapsed_label": _ms_label(elapsed_ms),
        "event_counts": dict(Counter(event.get("event_type", "unknown") for event in events)),
        "duration_totals": {key: round(value, 3) for key, value in totals.items()},
        "timeline": timeline,
        "slow_events": slow_events,
        "node_totals": node_rows,
        "errors": _build_errors(events, run_result),
    }


def _build_errors(
    events: list[dict[str, Any]],
    run_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for event in events:
        message = _error_message(event)
        if event.get("event_type") != "error" and not (event.get("ok") is False and message):
            continue
        errors.append(
            {
                "seq": event.get("seq"),
                "source": _event_label(event),
                "message": message,
            }
        )

    result_error = _run_result_error(run_result)
    if result_error:
        errors.append({"seq": None, "source": "run_result", "message": result_error})
    return errors
