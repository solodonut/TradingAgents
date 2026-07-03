"""Wrap LangGraph node callables to emit node_enter / node_exit events."""

from __future__ import annotations

import time
from collections.abc import Callable

from tradingagents.obs.run_logger import get_current_run_logger


def wrap_node(name: str, fn: Callable) -> Callable:
    def wrapped(state, *args, **kwargs):
        lg = get_current_run_logger()
        if lg is None:
            return fn(state, *args, **kwargs)
        lg.emit("node_enter", node=name)
        start = time.time()
        try:
            result = fn(state, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - log then re-raise; never swallow
            lg.emit("error", node=name, error_type=type(exc).__name__, message=str(exc))
            raise
        lg.emit("node_exit", node=name, elapsed_ms=(time.time() - start) * 1000)
        return result

    return wrapped
