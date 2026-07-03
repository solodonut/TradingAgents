"""Per-run structured JSONL logger + contextvar-based ambient access."""

from __future__ import annotations

import contextlib
import json
import os
import threading
import traceback
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REDACT_SUBSTRINGS = ("api_key", "authorization", "token", "secret", "password")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _looks_secret(key: str) -> bool:
    k = key.lower()
    return k.endswith("_key") or any(s in k for s in _REDACT_SUBSTRINGS)


def redact(obj: Any) -> Any:
    """Recursively mask values whose key name looks like a secret."""
    if isinstance(obj, dict):
        return {k: ("***" if _looks_secret(str(k)) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj


def truncate(value: Any, limit: int) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return {"text": value[:limit], "truncated": True, "full_chars": len(value)}
    return value


class RunLogger:
    """Thread-safe append-only JSONL writer for one analysis run.

    ``sink`` (optional) is invoked with each event dict after it is written to
    disk — the WebUI passes a function that pushes the event onto the SSE queue.
    A failing sink never propagates: the file remains the source of truth.
    """

    def __init__(
        self,
        run_id: str,
        ticker: str,
        path: str | Path,
        sink: Callable[[dict], None] | None = None,
        truncate_chars: int = 8000,
    ):
        self.run_id = run_id
        self.ticker = ticker
        self.path = Path(path)
        self._sink = sink
        self._truncate_chars = truncate_chars
        self._lock = threading.Lock()
        self._seq = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")  # noqa: SIM115

    def truncate(self, value: Any) -> Any:
        return truncate(value, self._truncate_chars)

    def emit(self, event_type: str, *, elapsed_ms: float | None = None, **payload) -> dict:
        with self._lock:
            self._seq += 1
            event: dict[str, Any] = {
                "ts": _now_iso(),
                "seq": self._seq,
                "run_id": self.run_id,
                "event_type": event_type,
            }
            if elapsed_ms is not None:
                event["elapsed_ms"] = elapsed_ms
            event.update(payload)
            self._fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            self._fh.flush()
        if self._sink is not None:
            try:
                self._sink(event)
            except Exception:  # noqa: BLE001 - sink failure must not break the run
                traceback.print_exc()
        return event

    def close(self) -> None:
        with self._lock, contextlib.suppress(Exception):
            self._fh.close()


_current: ContextVar[RunLogger | None] = ContextVar("run_logger", default=None)


def set_current_run_logger(logger: RunLogger | None) -> None:
    _current.set(logger)


def get_current_run_logger() -> RunLogger | None:
    return _current.get()


def clear_current_run_logger() -> None:
    _current.set(None)


def _default_log_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".tradingagents", "run_logs")


def build_log_path(log_dir: str, ticker: str, run_id: str, now: datetime | None = None) -> Path:
    now = now or datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in ticker) or "UNKNOWN"
    return Path(log_dir).expanduser() / f"{safe}_{stamp}_{run_id[:8]}.jsonl"


def create_run_logger(config: dict, run_id: str, ticker: str, sink=None) -> RunLogger | None:
    if not config.get("log_enabled", True):
        return None
    log_dir = config.get("log_dir") or _default_log_dir()
    path = build_log_path(log_dir, ticker, run_id)
    return RunLogger(
        run_id, ticker, path, sink=sink,
        truncate_chars=int(config.get("log_truncate_chars", 8000)),
    )
