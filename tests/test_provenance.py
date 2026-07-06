import pytest

from tradingagents.graph.evidence import EvidenceRegistry
from tradingagents.graph.provenance import (
    clear_current_evidence_registry,
    current_evidence_items,
    prefix_with_evidence,
    register_dataset_evidence,
    register_unavailable_evidence,
    set_current_evidence_registry,
)


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
        assert prefix_with_evidence("payload", citation_id, "OHLCV 数据集").startswith(
            "## [S1] OHLCV 数据集"
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
