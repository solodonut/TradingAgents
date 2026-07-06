import json
from types import SimpleNamespace

import pytest

from tradingagents.graph.evidence import EvidenceRegistry
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.provenance import (
    clear_current_evidence_registry,
    current_evidence_items,
    prefix_with_evidence,
    register_dataset_evidence,
    register_unavailable_evidence,
    set_current_evidence_registry,
    use_evidence_registry,
)
from tradingagents.graph.trading_graph import TradingAgentsGraph


@pytest.mark.unit
def test_context_registration_returns_snapshot_and_prefixes_text():
    registry = EvidenceRegistry()
    set_current_evidence_registry(registry)
    try:
        citation_id = register_dataset_evidence(
            kind="market_data",
            source_name="AKShare",
            title="get_stock_data: 600519",
            vendor="akshare",
            tool_name="get_stock_data",
            query={"ticker": "600519"},
            published_at="2026-06-29..2026-07-06",
        )
        assert citation_id == "S1"
        assert prefix_with_evidence("payload", citation_id, "OHLCV 数据集") == (
            "## [S1] OHLCV 数据集\n\npayload"
        )
        assert current_evidence_items()[0]["id"] == "S1"
    finally:
        clear_current_evidence_registry()


@pytest.mark.unit
def test_registration_is_noop_without_context():
    clear_current_evidence_registry()

    assert register_dataset_evidence(
        kind="market_data",
        source_name="AKShare",
        title="get_stock_data: 600519",
        vendor="akshare",
        tool_name="get_stock_data",
        query={"ticker": "600519"},
    ) is None
    assert current_evidence_items() == []


@pytest.mark.unit
def test_unavailable_evidence_can_be_registered():
    registry = EvidenceRegistry()
    set_current_evidence_registry(registry)
    try:
        citation_id = register_unavailable_evidence(
            tool_name="get_news",
            vendor="akshare",
            query={"ticker": "600519"},
            reason="DATA_SOURCE_UNAVAILABLE: network timeout",
        )
        assert citation_id == "S1"
        assert current_evidence_items()[0]["kind"] == "data_unavailable"
        assert current_evidence_items()[0]["title"] == "get_news unavailable"
    finally:
        clear_current_evidence_registry()


@pytest.mark.unit
def test_unavailable_evidence_uses_configured_vendors_without_vendor():
    registry = EvidenceRegistry()
    set_current_evidence_registry(registry)
    try:
        citation_id = register_unavailable_evidence(
            tool_name="get_news",
            query={"ticker": "600519"},
            reason="DATA_SOURCE_UNAVAILABLE: network timeout",
        )
        assert citation_id == "S1"
        assert current_evidence_items()[0]["source_name"] == "configured vendors"
    finally:
        clear_current_evidence_registry()


@pytest.mark.unit
def test_unavailable_evidence_is_noop_without_context():
    clear_current_evidence_registry()

    assert register_unavailable_evidence(
        tool_name="get_news",
        query={"ticker": "600519"},
        reason="DATA_SOURCE_UNAVAILABLE: network timeout",
    ) is None
    assert current_evidence_items() == []


@pytest.mark.unit
def test_nested_evidence_registry_context_restores_outer_registry():
    outer = EvidenceRegistry()
    inner = EvidenceRegistry()

    set_current_evidence_registry(outer)
    try:
        outer.register(
            kind="market_data",
            source_name="AKShare",
            title="outer",
            vendor="akshare",
            tool_name="get_stock_data",
            query={"ticker": "600519"},
        )
        outer_snapshot = current_evidence_items()

        with use_evidence_registry(inner):
            inner.register(
                kind="news",
                source_name="财联社",
                title="inner",
                vendor="akshare",
                tool_name="get_news",
                query={"ticker": "600519"},
            )
            assert current_evidence_items()[0]["title"] == "inner"

        assert current_evidence_items() == outer_snapshot
    finally:
        clear_current_evidence_registry()


@pytest.mark.unit
def test_initial_state_includes_evidence_items():
    state = Propagator().create_initial_state("600519", "2026-07-06")

    assert state["evidence_items"] == []


@pytest.mark.unit
def test_log_state_persists_evidence_items(tmp_path):
    graph = SimpleNamespace(
        log_states_dict={},
        ticker="600519",
        config={"results_dir": str(tmp_path)},
    )
    final_state = {
        "company_of_interest": "600519",
        "trade_date": "2026-07-06",
        "market_report": "market",
        "sentiment_report": "sentiment",
        "news_report": "news",
        "fundamentals_report": "fundamentals",
        "investment_debate_state": {
            "bull_history": "",
            "bear_history": "",
            "history": "",
            "current_response": "",
            "judge_decision": "",
        },
        "trader_investment_plan": "plan",
        "risk_debate_state": {
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "history": "",
            "judge_decision": "",
        },
        "investment_plan": "plan",
        "final_trade_decision": "Hold",
        "evidence_items": [
            {
                "id": "S1",
                "kind": "market_data",
                "source_name": "AKShare",
                "title": "get_stock_data: 600519",
                "vendor": "akshare",
                "tool_name": "get_stock_data",
                "query": {"ticker": "600519"},
                "url": "",
                "published_at": "",
                "excerpt": "",
            }
        ],
    }

    TradingAgentsGraph._log_state(graph, "2026-07-06", final_state)

    log_path = (
        tmp_path
        / "600519"
        / "TradingAgentsStrategy_logs"
        / "full_states_log_2026-07-06.json"
    )
    with open(log_path, encoding="utf-8") as handle:
        payload = json.load(handle)

    assert payload["evidence_items"][0]["id"] == "S1"
