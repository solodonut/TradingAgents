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
