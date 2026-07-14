"""Tests for markdown report assembly (api/reporting.py)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.reporting import build_markdown_report
from tradingagents.graph.evidence import EvidenceRegistry


@pytest.mark.unit
def test_build_markdown_report_resolves_label_citation_to_source_row():
    registry = EvidenceRegistry()
    registry.register(
        kind="market_data",
        source_name="AKShare",
        title="get_stock_data: 600519",
        vendor="akshare",
        tool_name="get_stock_data",
        query={"ticker": "600519"},
    )
    run = SimpleNamespace(
        ticker="600519",
        instrument_name="贵州茅台",
        trade_date="2026-07-06",
        decision="Hold",
        result={
            "market_report": "近期走强 [历史行情（OHLCV）]。",
            "evidence_items": registry.to_list(),
        },
    )

    report = build_markdown_report(run)

    # The label citation resolves S1, so a per-section source table is emitted.
    assert "### 引用来源" in report
    assert "| [历史行情（OHLCV）] | AKShare | get_stock_data: 600519 |" in report
    assert "## 全部数据来源" in report
