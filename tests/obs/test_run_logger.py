import json

from tradingagents.obs.run_logger import (
    RunLogger,
    clear_current_run_logger,
    get_current_run_logger,
    redact,
    set_current_run_logger,
)


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_emit_writes_jsonl_with_monotonic_seq(tmp_path):
    lg = RunLogger("run123", "SPY", tmp_path / "a.jsonl")
    lg.emit("run_start", ticker="SPY")
    lg.emit("node_enter", node="Trader")
    lg.close()
    events = _read(tmp_path / "a.jsonl")
    assert [e["seq"] for e in events] == [1, 2]
    assert events[0]["event_type"] == "run_start"
    assert events[0]["run_id"] == "run123"
    assert "ts" in events[0]
    assert events[1]["node"] == "Trader"


def test_truncate_long_strings(tmp_path):
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl", truncate_chars=5)
    out = lg.truncate("abcdefgh")
    assert out == {"text": "abcde", "truncated": True, "full_chars": 8}
    assert lg.truncate("abc") == "abc"
    lg.close()


def test_redact_masks_secret_keys():
    got = redact({"api_key": "sk-1", "openai_key": "x", "nested": {"authorization": "b", "ok": 1}})
    assert got == {"api_key": "***", "openai_key": "***", "nested": {"authorization": "***", "ok": 1}}


def test_sink_called_and_exception_swallowed(tmp_path):
    seen = []
    def bad_sink(ev):
        seen.append(ev)
        raise RuntimeError("boom")
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl", sink=bad_sink)
    ev = lg.emit("x", foo=1)  # must not raise
    lg.close()
    assert seen and seen[0]["foo"] == 1
    assert ev["event_type"] == "x"


def test_contextvar_set_get_clear(tmp_path):
    assert get_current_run_logger() is None
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    assert get_current_run_logger() is lg
    clear_current_run_logger()
    assert get_current_run_logger() is None
    lg.close()
