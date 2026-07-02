import queue
import threading

from api.runner import REPORT_SECTIONS, AnalysisRunner, chunk_to_events, debate_events


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


def test_runner_streams_validation_report_as_final_stage(tmp_path):
    from api.store import Store
    from api.telemetry import RunTelemetry

    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    telemetry = RunTelemetry("r1")
    fake = _FakeGraph(
        chunks=[
            {"final_trade_decision": "**Rating**: Buy"},
            {"validation_report": "## 报告一致性校验\n\n✅ 全部一致。"},
        ],
        final_state=None,
        decision=None,
    )
    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(store=store, event_queue=q, telemetry=telemetry)

    runner.run(run_id="r1", graph=fake, init_state={}, decision=None, final_state=None)

    events = _drain(q)
    assert any(
        e["event"] == "agent_status"
        and e["data"]["agent"] == "report_validator"
        and e["data"]["status"] == "done"
        for e in events
    )
    assert store.get_run("r1").result["validation_report"].startswith("## 报告一致性校验")
    snapshot = telemetry.snapshot(db_status="completed", process_alive=False)
    assert snapshot["last_report_section"] == "validation_report"


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


def test_invest_first_turn_is_bull_round_1():
    tracker: dict = {}
    events = debate_events(
        {"investment_debate_state": {"count": 1, "current_response": "Bull Analyst: buy it"}},
        tracker,
        {"invest_total": 2, "risk_total": 1},
    )
    assert len(events) == 1
    assert events[0]["event"] == "debate_round"
    assert events[0]["data"] == {
        "team": "invest",
        "round": 1,
        "total": 2,
        "speaker": "bull",
        "speaker_label": "多方",
        "content": "buy it",
    }
    assert tracker["invest_count"] == 1


def test_invest_second_turn_is_bear_same_round():
    tracker = {"invest_count": 1}
    events = debate_events(
        {"investment_debate_state": {"count": 2, "current_response": "Bear Analyst: no way"}},
        tracker,
        {"invest_total": 2, "risk_total": 1},
    )
    d = events[0]["data"]
    assert d["speaker"] == "bear" and d["speaker_label"] == "空方"
    assert d["round"] == 1 and d["content"] == "no way"


def test_invest_third_turn_is_round_2_bull():
    tracker = {"invest_count": 2}
    events = debate_events(
        {"investment_debate_state": {"count": 3, "current_response": "Bull Analyst: still buy"}},
        tracker,
        {"invest_total": 2, "risk_total": 1},
    )
    assert events[0]["data"]["round"] == 2
    assert events[0]["data"]["speaker"] == "bull"


def test_no_event_when_count_unchanged():
    tracker = {"invest_count": 2}
    events = debate_events(
        {"investment_debate_state": {"count": 2, "current_response": "Bear Analyst: no"}},
        tracker,
        {"invest_total": 2, "risk_total": 1},
    )
    assert events == []


def test_risk_speaker_cycle_and_round_math():
    tracker: dict = {}
    cfg = {"invest_total": 1, "risk_total": 2}
    e1 = debate_events(
        {"risk_debate_state": {
            "count": 1, "latest_speaker": "Aggressive",
            "current_aggressive_response": "Aggressive Analyst: go big"}},
        tracker, cfg)
    assert e1[0]["data"] == {
        "team": "risk", "round": 1, "total": 2,
        "speaker": "aggressive", "speaker_label": "激进", "content": "go big"}
    e2 = debate_events(
        {"risk_debate_state": {
            "count": 2, "latest_speaker": "Conservative",
            "current_conservative_response": "Conservative Analyst: careful"}},
        tracker, cfg)
    assert e2[0]["data"]["speaker"] == "conservative" and e2[0]["data"]["round"] == 1
    e3 = debate_events(
        {"risk_debate_state": {
            "count": 3, "latest_speaker": "Neutral",
            "current_neutral_response": "Neutral Analyst: middle"}},
        tracker, cfg)
    assert e3[0]["data"]["speaker"] == "neutral" and e3[0]["data"]["round"] == 1
    e4 = debate_events(
        {"risk_debate_state": {
            "count": 4, "latest_speaker": "Aggressive",
            "current_aggressive_response": "Aggressive Analyst: again"}},
        tracker, cfg)
    assert e4[0]["data"]["round"] == 2 and e4[0]["data"]["speaker"] == "aggressive"


def test_debate_events_ignores_chunk_without_debate_state():
    assert debate_events({"market_report": "x"}, {}, {"invest_total": 1, "risk_total": 1}) == []


def _drain(q: queue.Queue) -> list:
    out = []
    while True:
        item = q.get(timeout=2)
        if item is None:
            break
        out.append(item)
    return out
