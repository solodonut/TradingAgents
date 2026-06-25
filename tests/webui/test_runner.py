import queue
import threading

from api.runner import REPORT_SECTIONS, AnalysisRunner, chunk_to_events


def test_report_section_chunk_emits_report_event():
    events = chunk_to_events({"market_report": "## Market\nUp"}, set())
    types = [e["event"] for e in events]
    assert "report_section" in types
    report = next(e for e in events if e["event"] == "report_section")
    assert report["data"]["section"] == "market_report"
    assert report["data"]["content"] == "## Market\nUp"


def test_report_section_also_emits_agent_done():
    events = chunk_to_events({"market_report": "x"}, set())
    statuses = [e for e in events if e["event"] == "agent_status"]
    assert any(
        e["data"]["agent"] == "market_analyst" and e["data"]["status"] == "done"
        for e in statuses
    )


def test_empty_report_field_is_ignored():
    events = chunk_to_events({"market_report": ""}, set())
    assert events == []


def test_already_seen_section_not_re_emitted():
    seen = {"market_report"}
    events = chunk_to_events({"market_report": "x"}, seen)
    assert events == []


def test_all_known_sections_have_agent_mapping():
    for section in REPORT_SECTIONS:
        assert section in REPORT_SECTIONS
        agent, team = REPORT_SECTIONS[section]
        assert isinstance(agent, str) and isinstance(team, str)


class _FakeGraph:
    """Mimics TradingAgentsGraph: .graph.stream() yields chunks, then propagate-like end."""

    def __init__(self, chunks, final_state, decision):
        self._chunks = chunks
        self._final_state = final_state
        self._decision = decision

        class _Inner:
            def stream(inner_self, init_state, **kwargs):
                yield from chunks

        self.graph = _Inner()

    def propagator_create_initial_state(self, ticker, date):
        return {}


def test_runner_emits_done_and_calls_store(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})

    fake = _FakeGraph(
        chunks=[{"market_report": "m"}, {"final_trade_decision": "**Rating**: Buy"}],
        final_state={"final_trade_decision": "**Rating**: Buy", "market_report": "m"},
        decision="Buy",
    )
    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(store=store, event_queue=q)
    runner.run(
        run_id="r1",
        graph=fake,
        init_state={},
        decision="Buy",
        final_state={"final_trade_decision": "**Rating**: Buy", "market_report": "m"},
    )

    events = _drain(q)
    types = [e["event"] for e in events]
    assert "done" in types
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["decision"] == "Buy"
    assert store.get_run("r1").status == "completed"


def test_runner_persists_instrument_name_from_graph(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "SPY", "2024-05-10", "stock", {})

    fake = _FakeGraph(chunks=[{"market_report": "m"}], final_state=None, decision=None)
    fake._instrument_name = "SPDR S&P 500 ETF Trust"
    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(store=store, event_queue=q)

    runner.run(run_id="r1", graph=fake, init_state={}, decision=None, final_state=None)

    assert store.list_runs()[0].instrument_name == "SPDR S&P 500 ETF Trust"


def test_runner_without_instrument_name_does_not_error(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    # _FakeGraph has no _instrument_name attribute -> should be skipped silently.
    fake = _FakeGraph(chunks=[{"market_report": "m"}], final_state=None, decision=None)
    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(store=store, event_queue=q)

    runner.run(run_id="r1", graph=fake, init_state={}, decision=None, final_state=None)

    assert store.list_runs()[0].instrument_name is None


def test_runner_persists_partial_sections_while_running(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    fake = _FakeGraph(
        chunks=[{"market_report": "m"}, {"news_report": "n"}],
        final_state=None,
        decision=None,
    )
    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(store=store, event_queue=q)

    runner.run(run_id="r1", graph=fake, init_state={}, decision=None, final_state=None)

    row = store.get_run("r1")
    assert row.result["market_report"] == "m"
    assert row.result["news_report"] == "n"


def test_runner_updates_last_report_telemetry(tmp_path):
    from api.store import Store
    from api.telemetry import RunTelemetry

    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    telemetry = RunTelemetry("r1")
    fake = _FakeGraph(
        chunks=[{"market_report": "m"}, {"news_report": "n"}],
        final_state=None,
        decision=None,
    )
    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(store=store, event_queue=q, telemetry=telemetry)

    runner.run(run_id="r1", graph=fake, init_state={}, decision=None, final_state=None)

    snapshot = telemetry.snapshot(db_status="completed", process_alive=False)
    assert snapshot["last_report_section"] == "news_report"
    assert snapshot["last_report_at"] is not None


def test_runner_persists_partial_sections_before_completion(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    emitted = threading.Event()
    release = threading.Event()

    def chunks():
        yield {"market_report": "m"}
        emitted.set()
        release.wait(timeout=2)

    fake = _FakeGraph(chunks=chunks(), final_state=None, decision=None)
    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(store=store, event_queue=q)
    thread = threading.Thread(
        target=runner.run,
        kwargs={"run_id": "r1", "graph": fake, "init_state": {}, "decision": None, "final_state": None},
    )
    thread.start()

    assert emitted.wait(timeout=2)
    row = store.get_run("r1")
    assert row.status == "running"
    assert row.result == {"market_report": "m"}

    release.set()
    thread.join(timeout=2)


def test_runner_emits_error_on_exception(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})

    class _Boom:
        class graph:
            @staticmethod
            def stream(init_state, **kwargs):
                raise RuntimeError("kaboom")
                yield  # pragma: no cover

    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(store=store, event_queue=q)
    runner.run(run_id="r1", graph=_Boom(), init_state={}, decision=None, final_state=None)

    events = _drain(q)
    assert any(e["event"] == "error" for e in events)
    assert store.get_run("r1").status == "error"


def test_runner_emits_cancelled_when_cancel_event_is_set(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    cancel_event = threading.Event()

    def chunks():
        yield {"market_report": "m"}
        cancel_event.set()
        yield {"final_trade_decision": "**Rating**: Buy"}

    fake = _FakeGraph(chunks=chunks(), final_state=None, decision=None)
    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(store=store, event_queue=q, cancel_event=cancel_event)

    runner.run(run_id="r1", graph=fake, init_state={}, decision=None, final_state=None)

    events = _drain(q)
    assert any(e["event"] == "cancelled" for e in events)
    assert store.get_run("r1").status == "cancelled"


def _drain(q: queue.Queue) -> list:
    out = []
    while True:
        item = q.get(timeout=2)
        if item is None:
            break
        out.append(item)
    return out
