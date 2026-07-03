import json

from tradingagents.dataflows import interface
from tradingagents.obs.run_logger import (
    RunLogger,
    clear_current_run_logger,
    set_current_run_logger,
)


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_vendor_call_logged_on_success(tmp_path, monkeypatch):
    # Register a fake method+vendor so route_to_vendor takes the success path.
    monkeypatch.setitem(interface.VENDOR_METHODS, "fake_m", {"vA": lambda *a, **k: "RESULT"})
    monkeypatch.setattr(interface, "get_category_for_method", lambda m: "core_stock_apis")
    monkeypatch.setattr(interface, "get_vendor", lambda cat, m: "vA")
    monkeypatch.setattr(interface, "get_config", lambda: {"akshare_auto_route": False})

    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    assert interface.route_to_vendor("fake_m", "SPY") == "RESULT"
    lg.close()
    clear_current_run_logger()

    events = [e for e in _read(tmp_path / "a.jsonl") if e["event_type"] == "vendor_call"]
    assert len(events) == 1
    assert events[0]["method"] == "fake_m"
    assert events[0]["vendor"] == "vA"
    assert events[0]["ok"] is True


def test_vendor_call_no_logger_is_noop(tmp_path, monkeypatch):
    monkeypatch.setitem(interface.VENDOR_METHODS, "fake_m", {"vA": lambda *a, **k: "R"})
    monkeypatch.setattr(interface, "get_category_for_method", lambda m: "core_stock_apis")
    monkeypatch.setattr(interface, "get_vendor", lambda cat, m: "vA")
    monkeypatch.setattr(interface, "get_config", lambda: {"akshare_auto_route": False})
    clear_current_run_logger()
    assert interface.route_to_vendor("fake_m", "SPY") == "R"  # must not raise
