"""Scaffolding for the report validation node: schemas, state field, config flag."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.unit
def test_corrected_report_schema_defaults():
    from tradingagents.agents.schemas import CorrectedReport

    report = CorrectedReport(corrected_text="原样文本")
    assert report.corrected_text == "原样文本"
    assert report.corrections == []


@pytest.mark.unit
def test_correction_item_fields():
    from tradingagents.agents.schemas import CorrectionItem

    item = CorrectionItem(original="某基金", fixed="航空航天ETF天弘", reason="名称与权威身份不符")
    assert item.original == "某基金"
    assert item.fixed == "航空航天ETF天弘"
    assert item.reason


@pytest.mark.unit
def test_agent_state_has_validation_report():
    from tradingagents.agents.utils.agent_states import AgentState

    assert "validation_report" in AgentState.__annotations__


@pytest.mark.unit
def test_config_default_enables_validation():
    from tradingagents.default_config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["report_validation_enabled"] is True


@pytest.mark.unit
def test_env_override_disables_validation(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_REPORT_VALIDATION_ENABLED", "false")
    import tradingagents.default_config as dc

    reloaded = importlib.reload(dc)
    try:
        assert reloaded.DEFAULT_CONFIG["report_validation_enabled"] is False
    finally:
        monkeypatch.delenv("TRADINGAGENTS_REPORT_VALIDATION_ENABLED", raising=False)
        importlib.reload(dc)  # restore module global for later tests
