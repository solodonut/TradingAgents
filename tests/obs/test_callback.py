import json
import types
from types import SimpleNamespace

from tradingagents.obs.callback import ObsCallbackHandler
from tradingagents.obs.run_logger import (
    RunLogger,
    clear_current_run_logger,
    set_current_run_logger,
)


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_no_logger_context_is_noop():
    clear_current_run_logger()
    cb = ObsCallbackHandler()
    # Must not raise when no logger is in context.
    cb.on_llm_start({"name": "m"}, ["hi"], run_id="x")
    cb.on_llm_end(SimpleNamespace(generations=[], llm_output={}), run_id="x")


def test_llm_call_emitted_on_end(tmp_path):
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    cb = ObsCallbackHandler()
    cb.on_chat_model_start({"name": "gpt"}, [[SimpleNamespace(content="prompt text")]], run_id="u1")
    gen = SimpleNamespace(text="answer", message=SimpleNamespace(content="answer"))
    resp = SimpleNamespace(
        generations=[[gen]],
        llm_output={"token_usage": {"prompt_tokens": 3, "completion_tokens": 2}},
    )
    cb.on_llm_end(resp, run_id="u1")
    lg.close()
    clear_current_run_logger()
    events = [e for e in _read(tmp_path / "a.jsonl") if e["event_type"] == "llm_call"]
    assert len(events) == 1
    assert events[0]["response"] == "answer"
    assert events[0]["tokens"] == {"in": 3, "out": 2}
    assert "prompt text" in json.dumps(events[0]["prompt"])


def test_tool_call_emitted(tmp_path):
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    cb = ObsCallbackHandler()
    cb.on_tool_start({"name": "get_news"}, "AAPL", run_id="t1")
    cb.on_tool_end("some news", run_id="t1")
    lg.close()
    clear_current_run_logger()
    events = [e for e in _read(tmp_path / "a.jsonl") if e["event_type"] == "tool_call"]
    assert len(events) == 1
    assert events[0]["name"] == "get_news"
    assert events[0]["args"] == "AAPL"
    assert events[0]["result"] == "some news"


def test_on_llm_error_emits_error_event(tmp_path):
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    cb = ObsCallbackHandler()
    cb.on_llm_start({"name": "m"}, ["hi"], run_id="u1")
    cb.on_llm_error(ValueError("boom"), run_id="u1")
    lg.close()
    clear_current_run_logger()
    events = [e for e in _read(tmp_path / "a.jsonl") if e["event_type"] == "error"]
    assert len(events) == 1
    assert events[0]["phase"] == "llm"
    assert "u1" not in cb._llm


def test_on_tool_error_emits_error_and_cleans_up(tmp_path):
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    cb = ObsCallbackHandler()
    cb.on_tool_start({"name": "get_news"}, "AAPL", run_id="t1")
    cb.on_tool_error(RuntimeError("x"), run_id="t1")
    lg.close()
    clear_current_run_logger()
    events = [e for e in _read(tmp_path / "a.jsonl") if e["event_type"] == "error"]
    assert len(events) == 1
    assert events[0]["phase"] == "tool"
    assert "t1" not in cb._tool


def test_end_handlers_clean_up_state_even_without_logger(tmp_path):
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    cb = ObsCallbackHandler()
    cb.on_llm_start({"name": "m"}, ["p"], run_id="z")
    assert "z" in cb._llm
    clear_current_run_logger()
    cb.on_llm_end(types.SimpleNamespace(generations=[], llm_output={}), run_id="z")
    assert "z" not in cb._llm
