import json
from datetime import datetime

from tradingagents.obs.run_logger import (
    RunLogger,
    build_log_path,
    clear_current_run_logger,
    create_run_logger,
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


def test_build_log_path_format():
    p = build_log_path("/tmp/x", "SPY", "a1b2c3d4e5f6", now=datetime(2026, 7, 3, 14, 25, 30))
    assert p.name == "SPY_20260703-142530_a1b2c3d4.jsonl"
    assert str(p.parent) == "/tmp/x"


def test_create_run_logger_disabled_returns_none(tmp_path):
    cfg = {"log_enabled": False, "log_dir": str(tmp_path)}
    assert create_run_logger(cfg, "r", "SPY") is None


def test_create_run_logger_builds_logger(tmp_path):
    cfg = {"log_enabled": True, "log_dir": str(tmp_path), "log_truncate_chars": 10}
    lg = create_run_logger(cfg, "abcdef12", "QQQ")
    assert lg is not None
    assert lg.path.parent == tmp_path
    assert lg.truncate("x" * 20)["truncated"] is True
    lg.close()


def test_emit_non_serializable_payload_degrades_not_raises(tmp_path):
    """emit() must not raise when payload contains a non-JSON-serializable value.

    Upholds the 'logging never breaks the analysis' invariant (design spec §4.1).
    """
    from unittest.mock import MagicMock

    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    mock_val = MagicMock()
    # Must NOT raise TypeError
    lg.emit("run_end", decision=mock_val)
    lg.close()

    events = _read(tmp_path / "a.jsonl")
    assert len(events) == 1
    assert "decision" in events[0]
    # The value must be stored as a string (str fallback), not cause missing key
    assert isinstance(events[0]["decision"], str)
