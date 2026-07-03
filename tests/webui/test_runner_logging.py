import json
import queue

from api.runner import AnalysisRunner
from api.store import Store


class FakeGraph:
    """Minimal graph whose stream emits one report section."""

    config = {"max_debate_rounds": 1, "max_risk_discuss_rounds": 1}
    _stream_args = {}

    class _G:
        @staticmethod
        def stream(init_state, **kwargs):
            yield {"market_report": "hello market"}

    graph = _G()

    def process_signal(self, text):
        return "Hold"


def test_runner_emits_log_events_and_writes_file(tmp_path):
    store = Store(tmp_path / "webui.db")
    store.enqueue_run(run_id="r1", ticker="SPY", trade_date="2026-07-03",
                      asset_type="stock", config={})
    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(
        store=store, event_queue=q, cancel_event=None, telemetry=None,
        config={"log_enabled": True, "log_dir": str(tmp_path), "log_truncate_chars": 8000},
    )
    runner.run(run_id="r1", graph=FakeGraph(), init_state={}, decision=None, final_state=None)

    # Drain queue; at least one "log" event must be present (run_start).
    items = []
    while True:
        it = q.get()
        if it is None:
            break
        items.append(it)
    log_events = [i for i in items if i["event"] == "log"]
    assert log_events, "expected log SSE events"
    assert log_events[0]["data"]["event_type"] == "run_start"

    # A JSONL file was written and its path persisted.
    path = store.get_log_path("r1")
    assert path is not None
    with open(path, encoding="utf-8") as fh:
        types = [json.loads(line)["event_type"] for line in fh if line.strip()]
    assert "run_start" in types and "run_end" in types
