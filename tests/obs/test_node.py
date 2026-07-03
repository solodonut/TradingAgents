import json

import pytest

from tradingagents.obs.node import wrap_node
from tradingagents.obs.run_logger import (
    RunLogger,
    clear_current_run_logger,
    set_current_run_logger,
)


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_wrap_node_passthrough_without_logger():
    clear_current_run_logger()
    wrapped = wrap_node("Trader", lambda s: {"ok": s})
    assert wrapped(1) == {"ok": 1}


def test_wrap_node_emits_enter_exit(tmp_path):
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    wrapped = wrap_node("Trader", lambda s: {"v": 2})
    assert wrapped({}) == {"v": 2}
    lg.close()
    clear_current_run_logger()
    types = [e["event_type"] for e in _read(tmp_path / "a.jsonl")]
    assert types == ["node_enter", "node_exit"]


def test_wrap_node_emits_error_and_reraises(tmp_path):
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)

    def boom(_):
        raise ValueError("nope")

    with pytest.raises(ValueError):
        wrap_node("Trader", boom)({})
    lg.close()
    clear_current_run_logger()
    types = [e["event_type"] for e in _read(tmp_path / "a.jsonl")]
    assert types == ["node_enter", "error"]
