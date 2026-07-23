"""The report-validation node is wired into the graph after the Portfolio Manager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import tradingagents.graph.setup as setup_mod
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import GraphSetup


@pytest.mark.unit
def test_validator_node_present_and_flag_forwarded(monkeypatch):
    capture: dict = {}

    def fake_factory(llm, enabled=True):
        capture["enabled"] = enabled
        return lambda state: {"validation_report": ""}

    monkeypatch.setattr(setup_mod, "create_report_validator", fake_factory)

    gs = GraphSetup(
        quick_thinking_llm=MagicMock(),
        deep_thinking_llm=MagicMock(),
        tool_nodes={"market": MagicMock()},
        conditional_logic=ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1),
        analyst_concurrency_limit=1,
        report_validation_enabled=False,
    )
    workflow = gs.setup_graph(("market",))

    assert "Report Validator" in workflow.nodes
    assert capture["enabled"] is False
    # Compiles without error with the extra node + edges.
    workflow.compile()


@pytest.mark.unit
def test_debate_and_risk_edges_map_every_router_target(monkeypatch):
    class RecordingStateGraph:
        def __init__(self, _state_type):
            self.nodes: dict[str, object] = {}
            self.conditional_edges: dict[str, dict[str, str]] = {}

        def add_node(self, name, node):
            self.nodes[name] = node

        def add_edge(self, _source, _target):
            return None

        def add_conditional_edges(self, source, _router, path_map):
            if isinstance(path_map, dict):
                self.conditional_edges[source] = path_map

    def fake_node_factory(*_args, **_kwargs):
        return lambda state: state

    monkeypatch.setattr(setup_mod, "StateGraph", RecordingStateGraph)
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
        monkeypatch.setattr(setup_mod, factory_name, fake_node_factory)

    gs = GraphSetup(
        quick_thinking_llm=MagicMock(),
        deep_thinking_llm=MagicMock(),
        tool_nodes={"market": MagicMock()},
        conditional_logic=ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1),
    )
    workflow = gs.setup_graph(("market",))

    debate_targets = {
        "Bull Researcher": "Bull Researcher",
        "Bear Researcher": "Bear Researcher",
        "Research Manager": "Research Manager",
    }
    risk_targets = {
        "Aggressive Analyst": "Aggressive Analyst",
        "Conservative Analyst": "Conservative Analyst",
        "Neutral Analyst": "Neutral Analyst",
        "Portfolio Manager": "Portfolio Manager",
    }

    assert workflow.conditional_edges["Bull Researcher"] == debate_targets
    assert workflow.conditional_edges["Bear Researcher"] == debate_targets
    assert workflow.conditional_edges["Aggressive Analyst"] == risk_targets
    assert workflow.conditional_edges["Conservative Analyst"] == risk_targets
    assert workflow.conditional_edges["Neutral Analyst"] == risk_targets
