import json
from pathlib import Path

from tradingagents.obs import run_logger as rl


def test_propagate_creates_run_log(tmp_path, monkeypatch):
    """propagate wraps _run_graph with a RunLogger when none is in context."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    # Build a minimal fake that reuses only the logging wrapper logic.
    class FakeGraph(TradingAgentsGraph):
        def __init__(self):  # bypass heavy __init__
            self.config = {"log_enabled": True, "log_dir": str(tmp_path), "log_truncate_chars": 8000}
            self._checkpointer_ctx = None

        def _resolve_pending_entries(self, t):
            pass

        def _run_graph(self, company_name, trade_date, asset_type="stock"):
            # Inside the run, a logger must be active.
            assert rl.get_current_run_logger() is not None
            return ({"final_trade_decision": "BUY"}, "BUY")

    g = FakeGraph()
    final_state, signal = g.propagate("SPY", "2026-07-03")
    assert signal == "BUY"
    assert rl.get_current_run_logger() is None  # cleared afterwards

    files = list(Path(tmp_path).glob("SPY_*.jsonl"))
    assert len(files) == 1
    types = [json.loads(line)["event_type"] for line in files[0].read_text().splitlines() if line]
    assert types[0] == "run_start"
    assert "run_end" in types
