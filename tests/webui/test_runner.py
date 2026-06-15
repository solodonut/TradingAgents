from api.runner import REPORT_SECTIONS, chunk_to_events


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


import queue

from api.runner import AnalysisRunner


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


def _drain(q: queue.Queue) -> list:
    out = []
    while True:
        item = q.get(timeout=2)
        if item is None:
            break
        out.append(item)
    return out
