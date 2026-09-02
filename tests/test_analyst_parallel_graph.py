"""Analysts running concurrently inside one run (``analyst_concurrency_limit``).

Three properties of the parallel wiring are load-bearing and easy to break:

1. A wave must fan **in** through a ``defer=True`` barrier. Analysts take
   different numbers of tool rounds, so a plain fan-in fires when the fastest
   branch lands and the whole downstream pipeline runs again for the slow ones.
2. ``evidence_items`` needs a reducer. Every analyst writes a full registry
   snapshot, and two writes in one super-step raise ``InvalidUpdateError`` on a
   LastValue channel.
3. Each analyst needs a private message channel, or their tool-call turns
   interleave in one list and the routers/ToolNodes pick up someone else's turn.

The tests below drive a real compiled graph with fake analyst nodes, plus a
recording-StateGraph shape check that ``concurrency_limit=1`` still produces the
old serial graph edge for edge.
"""

from __future__ import annotations

import threading
from collections import Counter
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START

import tradingagents.graph.setup as setup_mod
from tradingagents.agents.utils.agent_states import merge_evidence_items
from tradingagents.graph.analyst_execution import ANALYST_NODE_SPECS
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.evidence import EvidenceRegistry
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.setup import GraphSetup

ALL_ANALYSTS = ("market", "social", "news", "fundamentals")

# Analysts that ask for one tool round before reporting. Mixing these with
# zero-round analysts is what makes the wave lengths unequal, which is the only
# way the missing-barrier bug shows up.
TOOL_ROUND_ANALYSTS = frozenset({"market", "fundamentals"})


# --- fake nodes -----------------------------------------------------------


def _fake_analyst(spec, seen: dict[str, list[str]], tool_rounds: int):
    """An analyst that optionally asks for a tool, then writes its report."""
    messages_key = spec.messages_key

    def node(state):
        own = state[messages_key]
        seen.setdefault(spec.key, []).extend(
            str(getattr(m, "content", m)) for m in own
        )
        tool_replies = sum(1 for m in own if isinstance(m, ToolMessage))
        if tool_replies < tool_rounds:
            call_id = f"{spec.key}-call-{tool_replies}"
            return {
                messages_key: [
                    AIMessage(
                        content=f"{spec.key} wants a tool",
                        tool_calls=[
                            {"name": f"get_{spec.key}", "args": {}, "id": call_id}
                        ],
                    )
                ]
            }
        return {
            messages_key: [AIMessage(content=f"{spec.key} done")],
            spec.report_key: f"{spec.key} report",
            # Every analyst writes a full snapshot of the shared registry, so
            # concurrent writes overlap and must be merged, not rejected.
            "evidence_items": [{"id": f"S{spec.key}", "source": spec.key}],
        }

    return node


def _fake_tool_node(spec):
    def node(state):
        last = state[spec.messages_key][-1]
        return {
            spec.messages_key: [
                ToolMessage(
                    content=f"{spec.key} tool result",
                    tool_call_id=last.tool_calls[0]["id"],
                )
            ]
        }

    return node


def _downstream_nodes(counts: Counter):
    """Fake post-analyst nodes that short-circuit both debates to one turn."""

    def counting(name, update=None):
        def node(_state):
            counts[name] += 1
            return dict(update or {})

        return node

    # count >= 2 * max_debate_rounds(1) sends the router straight to the manager.
    bull = counting(
        "Bull Researcher",
        {
            "investment_debate_state": {
                "bull_history": "b",
                "bear_history": "",
                "history": "b",
                "current_response": "Bull says buy",
                "judge_decision": "",
                "count": 2,
            }
        },
    )
    aggressive = counting(
        "Aggressive Analyst",
        {
            "risk_debate_state": {
                "aggressive_history": "a",
                "conservative_history": "",
                "neutral_history": "",
                "history": "a",
                "latest_speaker": "Aggressive",
                "current_aggressive_response": "a",
                "current_conservative_response": "",
                "current_neutral_response": "",
                "judge_decision": "",
                "count": 3,
            }
        },
    )
    return {
        "create_bull_researcher": bull,
        "create_bear_researcher": counting("Bear Researcher"),
        "create_research_manager": counting(
            "Research Manager", {"investment_plan": "plan"}
        ),
        "create_trader": counting("Trader", {"trader_investment_plan": "trade"}),
        "create_aggressive_debator": aggressive,
        "create_conservative_debator": counting("Conservative Analyst"),
        "create_neutral_debator": counting("Neutral Analyst"),
        "create_portfolio_manager": counting(
            "Portfolio Manager", {"final_trade_decision": "BUY"}
        ),
        "create_report_validator": counting("Report Validator"),
    }


def _build_graph(monkeypatch, concurrency_limit: int):
    """Compile a real graph whose LLM-backed nodes are replaced by fakes."""
    seen: dict[str, list[str]] = {}
    counts: Counter = Counter()

    for factory_name, node in _downstream_nodes(counts).items():
        monkeypatch.setattr(setup_mod, factory_name, lambda *_a, _n=node, **_kw: _n)
    # Msg-clear only matters for trimming; a passthrough keeps the graph honest
    # about which channel each analyst owns without deleting the fake turns.
    monkeypatch.setattr(setup_mod, "create_msg_delete", lambda *_a, **_kw: lambda _s: {})

    analyst_factories = {
        "market": "create_market_analyst",
        "social": "create_sentiment_analyst",
        "news": "create_news_analyst",
        "fundamentals": "create_fundamentals_analyst",
    }
    for key, factory_name in analyst_factories.items():
        spec = ANALYST_NODE_SPECS[key]
        rounds = 1 if key in TOOL_ROUND_ANALYSTS else 0
        monkeypatch.setattr(
            setup_mod,
            factory_name,
            lambda *_a, _spec=spec, _r=rounds, **_kw: _fake_analyst(_spec, seen, _r),
        )

    gs = GraphSetup(
        quick_thinking_llm=MagicMock(),
        deep_thinking_llm=MagicMock(),
        tool_nodes={key: _fake_tool_node(ANALYST_NODE_SPECS[key]) for key in ALL_ANALYSTS},
        conditional_logic=ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1),
        analyst_concurrency_limit=concurrency_limit,
    )
    return gs.setup_graph(ALL_ANALYSTS).compile(), seen, counts


def _initial_state():
    return Propagator().create_initial_state("NVDA", "2026-01-15")


# --- end-to-end parallel run ---------------------------------------------


@pytest.mark.unit
def test_parallel_wave_produces_every_report(monkeypatch):
    graph, _seen, _counts = _build_graph(monkeypatch, concurrency_limit=4)

    final = graph.invoke(_initial_state())

    for key in ALL_ANALYSTS:
        assert final[ANALYST_NODE_SPECS[key].report_key] == f"{key} report"
    assert final["final_trade_decision"] == "BUY"


@pytest.mark.unit
def test_downstream_runs_once_despite_unequal_branch_lengths(monkeypatch):
    """Regression for the missing ``defer=True`` barrier.

    Without it the join fires when the zero-tool-round analysts land, and every
    node after the analysts executes a second time once the slow branches
    finish.
    """
    graph, _seen, counts = _build_graph(monkeypatch, concurrency_limit=4)

    graph.invoke(_initial_state())

    for name in (
        "Bull Researcher",
        "Research Manager",
        "Trader",
        "Aggressive Analyst",
        "Portfolio Manager",
        "Report Validator",
    ):
        assert counts[name] == 1, f"{name} ran {counts[name]} times, expected exactly 1"


@pytest.mark.unit
def test_concurrent_analysts_merge_evidence_instead_of_conflicting(monkeypatch):
    """Two analysts writing ``evidence_items`` in one super-step must merge.

    On a LastValue channel this run raises ``InvalidUpdateError``.
    """
    graph, _seen, _counts = _build_graph(monkeypatch, concurrency_limit=4)

    final = graph.invoke(_initial_state())

    assert sorted(item["id"] for item in final["evidence_items"]) == [
        "Sfundamentals",
        "Smarket",
        "Snews",
        "Ssocial",
    ]


@pytest.mark.unit
def test_each_analyst_only_sees_its_own_channel(monkeypatch):
    graph, seen, _counts = _build_graph(monkeypatch, concurrency_limit=4)

    graph.invoke(_initial_state())

    for key in ALL_ANALYSTS:
        others = [other for other in ALL_ANALYSTS if other != key]
        blob = " ".join(seen[key])
        assert "NVDA" in blob  # its own seeded opening turn
        for other in others:
            assert other not in blob, f"{key} saw {other}'s messages: {blob}"


# --- zero-regression guard for the default (serial) path -----------------


class _RecordingStateGraph:
    """Captures nodes/edges so the serial graph shape can be compared exactly."""

    def __init__(self, _state_type):
        self.nodes: dict[str, object] = {}
        self.deferred: set[str] = set()
        self.edges: set[tuple[str, str]] = set()
        self.conditional_edges: list[tuple[str, object]] = []

    def add_node(self, name, node, defer: bool = False):
        self.nodes[name] = node
        if defer:
            self.deferred.add(name)

    def add_edge(self, source, target):
        self.edges.add((source, target))

    def add_conditional_edges(self, source, _router, path_map):
        self.conditional_edges.append((source, tuple(path_map)))


def _record_shape(monkeypatch, concurrency_limit: int) -> _RecordingStateGraph:
    monkeypatch.setattr(setup_mod, "StateGraph", _RecordingStateGraph)
    for factory_name in (
        "create_market_analyst",
        "create_sentiment_analyst",
        "create_news_analyst",
        "create_fundamentals_analyst",
        "create_bull_researcher",
        "create_bear_researcher",
        "create_research_manager",
        "create_trader",
        "create_aggressive_debator",
        "create_neutral_debator",
        "create_conservative_debator",
        "create_portfolio_manager",
        "create_report_validator",
        "create_msg_delete",
    ):
        monkeypatch.setattr(setup_mod, factory_name, lambda *_a, **_kw: (lambda s: s))

    gs = GraphSetup(
        quick_thinking_llm=MagicMock(),
        deep_thinking_llm=MagicMock(),
        tool_nodes=dict.fromkeys(ALL_ANALYSTS, MagicMock()),
        conditional_logic=ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1),
        analyst_concurrency_limit=concurrency_limit,
    )
    return gs.setup_graph(ALL_ANALYSTS)


@pytest.mark.unit
def test_serial_default_keeps_the_pre_parallel_graph_shape(monkeypatch):
    """``concurrency_limit=1`` (the default) must not change the graph at all."""
    workflow = _record_shape(monkeypatch, concurrency_limit=1)

    assert workflow.deferred == set()
    assert not any(name.startswith("Analyst Wave") for name in workflow.nodes)

    # The full edge set, so an accidental extra hop shows up here rather than in
    # a live run. Conditional edges are recorded separately, below.
    assert workflow.edges == {
        (START, "Market Analyst"),
        ("tools_market", "Market Analyst"),
        ("Msg Clear Market", "Sentiment Analyst"),
        ("tools_social", "Sentiment Analyst"),
        ("Msg Clear Sentiment", "News Analyst"),
        ("tools_news", "News Analyst"),
        ("Msg Clear News", "Fundamentals Analyst"),
        ("tools_fundamentals", "Fundamentals Analyst"),
        ("Msg Clear Fundamentals", "Bull Researcher"),
        ("Research Manager", "Trader"),
        ("Trader", "Aggressive Analyst"),
        ("Portfolio Manager", "Report Validator"),
        ("Report Validator", END),
    }
    assert workflow.conditional_edges[:4] == [
        ("Market Analyst", ("tools_market", "Msg Clear Market")),
        ("Sentiment Analyst", ("tools_social", "Msg Clear Sentiment")),
        ("News Analyst", ("tools_news", "Msg Clear News")),
        ("Fundamentals Analyst", ("tools_fundamentals", "Msg Clear Fundamentals")),
    ]


@pytest.mark.unit
def test_parallel_limit_adds_one_deferred_join_per_wave(monkeypatch):
    workflow = _record_shape(monkeypatch, concurrency_limit=2)

    # Two waves of two analysts, so two barriers, both deferred.
    assert workflow.deferred == {"Analyst Wave 1 Join", "Analyst Wave 2 Join"}
    assert ("Msg Clear Market", "Analyst Wave 1 Join") in workflow.edges
    assert ("Msg Clear Sentiment", "Analyst Wave 1 Join") in workflow.edges
    # Wave 2 fans out from the wave-1 barrier, not from an individual analyst.
    assert ("Analyst Wave 1 Join", "News Analyst") in workflow.edges
    assert ("Analyst Wave 1 Join", "Fundamentals Analyst") in workflow.edges
    assert ("Analyst Wave 2 Join", "Bull Researcher") in workflow.edges


# --- evidence registry / reducer ----------------------------------------


@pytest.mark.unit
def test_registry_assigns_unique_ids_under_concurrent_registration():
    """The union-by-id reducer is only correct while ids stay unique."""
    registry = EvidenceRegistry([])
    ids: list[str] = []
    lock = threading.Lock()
    start = threading.Barrier(8)

    def register(index: int):
        start.wait()
        for offset in range(25):
            citation = registry.register(
                source_type="tool",
                title=f"src-{index}-{offset}",
                url=f"https://example.com/{index}/{offset}",
            )
            with lock:
                ids.append(citation)

    threads = [threading.Thread(target=register, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(ids) == 200
    assert len(set(ids)) == 200
    assert len({item["id"] for item in registry.to_list()}) == 200


@pytest.mark.unit
def test_merge_evidence_items_unions_by_id_and_keeps_first_seen_order():
    left = [{"id": "S1", "title": "a"}, {"id": "S2", "title": "b"}]
    right = [{"id": "S2", "title": "b-dupe"}, {"id": "S3", "title": "c"}]

    merged = merge_evidence_items(left, right)

    assert [item["id"] for item in merged] == ["S1", "S2", "S3"]
    # First writer wins for an overlapping id, so a snapshot cannot be rewritten.
    assert merged[1]["title"] == "b"
    assert merge_evidence_items(None, None) == []
    assert merge_evidence_items(left, None) == left
