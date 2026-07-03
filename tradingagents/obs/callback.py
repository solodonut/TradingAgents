"""LangChain callback → RunLogger llm_call / tool_call events (contextvar-based)."""

from __future__ import annotations

import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from tradingagents.obs.run_logger import get_current_run_logger


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part) for part in content)
    return str(content)


def _messages_text(messages: list) -> str:
    flat = [m for batch in messages for m in batch]
    return "\n\n".join(_content_text(getattr(m, "content", m)) for m in flat)


def _model_from(serialized: dict | None, kwargs: dict) -> str | None:
    params = kwargs.get("invocation_params") or {}
    for key in ("model", "model_name"):
        if params.get(key):
            return str(params[key])
    if serialized:
        blob = serialized.get("kwargs") or {}
        for key in ("model", "model_name"):
            if blob.get(key):
                return str(blob[key])
        name = serialized.get("name") or serialized.get("id")
        if name:
            return str(name)
    return None


class ObsCallbackHandler(BaseCallbackHandler):
    """Emits llm_call / tool_call events when a RunLogger is in context.

    Keyed on LangChain's per-invocation ``run_id`` so concurrent calls (the
    analyst concurrency path) don't cross their timings.
    """

    def __init__(self) -> None:
        self._llm: dict[Any, dict] = {}
        self._tool: dict[Any, dict] = {}

    def on_llm_start(self, serialized, prompts, *, run_id=None, **kwargs) -> None:
        if get_current_run_logger() is None:
            return
        self._llm[run_id] = {
            "t": time.time(),
            "model": _model_from(serialized, kwargs),
            "prompt": "\n\n".join(str(p) for p in (prompts or [])),
        }

    def on_chat_model_start(self, serialized, messages, *, run_id=None, **kwargs) -> None:
        if get_current_run_logger() is None:
            return
        self._llm[run_id] = {
            "t": time.time(),
            "model": _model_from(serialized, kwargs),
            "prompt": _messages_text(messages),
        }

    def on_llm_end(self, response, *, run_id=None, **kwargs) -> None:
        start = self._llm.pop(run_id, None) or {}  # clean up regardless of logger state
        lg = get_current_run_logger()
        if lg is None:
            return
        elapsed = (time.time() - start["t"]) * 1000 if start.get("t") else None
        text = ""
        try:
            parts = []
            for batch in getattr(response, "generations", []) or []:
                for gen in batch:
                    parts.append(getattr(gen, "text", "") or _content_text(
                        getattr(getattr(gen, "message", None), "content", "")))
            text = "\n".join(p for p in parts if p)
        except Exception:  # noqa: BLE001
            text = str(response)
        tokens: dict = {}
        try:
            usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
            tokens = {"in": usage.get("prompt_tokens"), "out": usage.get("completion_tokens")}
        except Exception:  # noqa: BLE001
            pass
        lg.emit(
            "llm_call",
            model=start.get("model"),
            prompt=lg.truncate(start.get("prompt", "")),
            response=lg.truncate(text),
            tokens=tokens,
            elapsed_ms=elapsed,
        )

    def on_llm_error(self, error, *, run_id=None, **kwargs) -> None:
        self._llm.pop(run_id, None)  # clean up regardless of logger state
        lg = get_current_run_logger()
        if lg is None:
            return
        lg.emit("error", phase="llm", error_type=type(error).__name__, message=str(error))

    def on_tool_start(self, serialized, input_str, *, run_id=None, **kwargs) -> None:
        if get_current_run_logger() is None:
            return
        self._tool[run_id] = {
            "t": time.time(),
            "name": (serialized or {}).get("name"),
            "args": input_str,
        }

    def on_tool_end(self, output, *, run_id=None, **kwargs) -> None:
        start = self._tool.pop(run_id, None) or {}  # clean up regardless of logger state
        lg = get_current_run_logger()
        if lg is None:
            return
        elapsed = (time.time() - start["t"]) * 1000 if start.get("t") else None
        lg.emit(
            "tool_call",
            name=start.get("name"),
            args=lg.truncate(str(start.get("args", ""))),
            result=lg.truncate(_content_text(output)),
            elapsed_ms=elapsed,
        )

    def on_tool_error(self, error, *, run_id=None, **kwargs) -> None:
        self._tool.pop(run_id, None)  # clean up regardless of logger state
        lg = get_current_run_logger()
        if lg is None:
            return
        lg.emit("error", phase="tool", error_type=type(error).__name__, message=str(error))
