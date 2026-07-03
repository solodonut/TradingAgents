"""Wrap LangGraph node callables to emit node_enter / node_exit events."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from tradingagents.obs.run_logger import get_current_run_logger


def _invoke_node(fn: Any, state, *args, **kwargs):
    if callable(fn):
        return fn(state, *args, **kwargs)
    invoke = getattr(fn, "invoke", None)
    if invoke is not None:
        return invoke(state, *args, **kwargs)
    return fn(state, *args, **kwargs)


def wrap_node(name: str, fn: Any) -> Callable:
    def wrapped(state, *args, **kwargs):
        lg = get_current_run_logger()
        if lg is None:
            return _invoke_node(fn, state, *args, **kwargs)
        lg.emit("node_enter", node=name)
        start = time.time()
        try:
            result = _invoke_node(fn, state, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - log then re-raise; never swallow
            lg.emit("error", node=name, error_type=type(exc).__name__, message=str(exc))
            raise
        lg.emit("node_exit", node=name, elapsed_ms=(time.time() - start) * 1000)
        return result

    return wrapped
