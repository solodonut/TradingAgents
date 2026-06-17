"""In-memory runtime telemetry for WebUI analysis runs."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part) for part in content)
    return str(content)


def _prompt_preview(prompts: list[Any]) -> tuple[str, int]:
    text = "\n\n".join(_message_text(p) for p in prompts)
    return text[:1200], len(text)


def _model_from(serialized: dict[str, Any] | None, kwargs: dict[str, Any]) -> str | None:
    params = kwargs.get("invocation_params") or {}
    for key in ("model", "model_name"):
        if params.get(key):
            return str(params[key])
    if serialized:
        kwargs_blob = serialized.get("kwargs") or {}
        for key in ("model", "model_name"):
            if kwargs_blob.get(key):
                return str(kwargs_blob[key])
        name = serialized.get("name") or serialized.get("id")
        if name:
            return str(name)
    return None


class RunTelemetry:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {
            "run_id": run_id,
            "created_at": _now(),
            "updated_at": _now(),
            "llm_active": False,
            "active_llm_calls": 0,
            "last_llm_start_at": None,
            "last_llm_end_at": None,
            "last_llm_error_at": None,
            "last_llm_error": None,
            "last_llm_model": None,
            "last_prompt_preview": None,
            "last_prompt_chars": None,
            "last_report_section": None,
            "last_report_at": None,
        }

    def callback_handler(self) -> BaseCallbackHandler:
        return RunTelemetryCallback(self)

    def snapshot(self, *, db_status: str | None, process_alive: bool) -> dict[str, Any]:
        with self._lock:
            data = dict(self._data)
        data["db_status"] = db_status
        data["process_alive"] = process_alive
        return data

    def mark_llm_start(
        self,
        *,
        model: str | None,
        prompt_preview: str,
        prompt_chars: int,
    ) -> None:
        with self._lock:
            self._data["active_llm_calls"] += 1
            self._data["llm_active"] = True
            self._data["last_llm_start_at"] = _now()
            self._data["last_llm_model"] = model
            self._data["last_prompt_preview"] = prompt_preview
            self._data["last_prompt_chars"] = prompt_chars
            self._data["updated_at"] = _now()

    def mark_llm_end(self) -> None:
        with self._lock:
            self._data["active_llm_calls"] = max(0, self._data["active_llm_calls"] - 1)
            self._data["llm_active"] = self._data["active_llm_calls"] > 0
            self._data["last_llm_end_at"] = _now()
            self._data["updated_at"] = _now()

    def mark_llm_error(self, error: BaseException) -> None:
        with self._lock:
            self._data["active_llm_calls"] = max(0, self._data["active_llm_calls"] - 1)
            self._data["llm_active"] = self._data["active_llm_calls"] > 0
            self._data["last_llm_error_at"] = _now()
            self._data["last_llm_error"] = str(error)
            self._data["updated_at"] = _now()

    def mark_report(self, section: str) -> None:
        with self._lock:
            self._data["last_report_section"] = section
            self._data["last_report_at"] = _now()
            self._data["updated_at"] = _now()


class RunTelemetryCallback(BaseCallbackHandler):
    def __init__(self, telemetry: RunTelemetry):
        self._telemetry = telemetry

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        preview, chars = _prompt_preview(list(prompts))
        self._telemetry.mark_llm_start(
            model=_model_from(serialized, kwargs),
            prompt_preview=preview,
            prompt_chars=chars,
        )

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        **kwargs: Any,
    ) -> None:
        flat = [msg for batch in messages for msg in batch]
        preview, chars = _prompt_preview(flat)
        self._telemetry.mark_llm_start(
            model=_model_from(serialized, kwargs),
            prompt_preview=preview,
            prompt_chars=chars,
        )

    def on_llm_end(self, *args: Any, **kwargs: Any) -> None:
        self._telemetry.mark_llm_end()

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        self._telemetry.mark_llm_error(error)
