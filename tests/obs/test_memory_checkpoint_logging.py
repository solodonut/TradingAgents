import json

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.obs.run_logger import (
    RunLogger,
    clear_current_run_logger,
    set_current_run_logger,
)


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_store_decision_emits_memory_op(tmp_path):
    mem = TradingMemoryLog({"memory_log_path": str(tmp_path / "mem.md"), "memory_log_max_entries": None})
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    mem.store_decision(ticker="SPY", trade_date="2026-07-03", final_trade_decision="BUY")
    lg.close()
    clear_current_run_logger()
    ops = [e for e in _read(tmp_path / "a.jsonl") if e["event_type"] == "memory_op"]
    assert any(o["op"] == "append" and o["ticker"] == "SPY" for o in ops)


def test_get_past_context_emits_inject(tmp_path):
    mem = TradingMemoryLog({"memory_log_path": str(tmp_path / "mem.md"), "memory_log_max_entries": None})
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    mem.get_past_context("SPY")
    lg.close()
    clear_current_run_logger()
    ops = [e for e in _read(tmp_path / "a.jsonl") if e["event_type"] == "memory_op"]
    assert any(o["op"] == "inject" for o in ops)
