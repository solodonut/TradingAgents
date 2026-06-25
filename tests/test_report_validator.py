"""Tests for the post-decision report validation node."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import tradingagents.graph.report_validator as rv
from tradingagents.agents.schemas import CorrectedReport, CorrectionItem


def _structured_llm(invoke_return=None, invoke_side_effect=None):
    """Build a fake llm whose with_structured_output(...).invoke(...) is controlled."""
    structured = MagicMock()
    if invoke_side_effect is not None:
        structured.invoke.side_effect = invoke_side_effect
    else:
        structured.invoke.return_value = invoke_return
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm, structured


def _state(**reports):
    base = {
        "company_of_interest": "159241",
        "trade_date": "2026-06-25",
        "instrument_context": "Resolved identity: 航空航天ETF天弘 ...",
    }
    base.update(reports)
    return base


@pytest.mark.unit
def test_corrects_wrong_name(monkeypatch):
    monkeypatch.setattr(rv, "build_verified_market_snapshot", lambda s, d: "SNAPSHOT")
    llm, _ = _structured_llm(
        invoke_return=CorrectedReport(
            corrected_text="航空航天ETF天弘 近期走强。",
            corrections=[CorrectionItem(original="某基金", fixed="航空航天ETF天弘", reason="名称与权威身份不符")],
        )
    )
    node = rv.create_report_validator(llm, enabled=True)
    out = node(_state(market_report="某基金 近期走强。"))

    assert out["market_report"] == "航空航天ETF天弘 近期走强。"
    assert "航空航天ETF天弘" in out["validation_report"]
    assert "某基金" in out["validation_report"]


@pytest.mark.unit
def test_no_change_when_already_correct(monkeypatch):
    monkeypatch.setattr(rv, "build_verified_market_snapshot", lambda s, d: "SNAPSHOT")
    llm, _ = _structured_llm(
        invoke_return=CorrectedReport(corrected_text="原文不变。", corrections=[])
    )
    node = rv.create_report_validator(llm, enabled=True)
    out = node(_state(market_report="原文不变。"))

    assert "market_report" not in out  # unchanged -> not written back
    assert "✅" in out["validation_report"]


@pytest.mark.unit
def test_snapshot_unavailable_skips_number_dimension(monkeypatch):
    def boom(symbol, date):
        raise ValueError("no data")

    monkeypatch.setattr(rv, "build_verified_market_snapshot", boom)
    llm, _ = _structured_llm(
        invoke_return=CorrectedReport(corrected_text="X", corrections=[])
    )
    node = rv.create_report_validator(llm, enabled=True)
    out = node(_state(market_report="X"))

    assert "market_report" not in out
    assert "快照不可用" in out["validation_report"]


@pytest.mark.unit
def test_disabled_passthrough_makes_no_llm_call():
    llm = MagicMock()
    node = rv.create_report_validator(llm, enabled=False)
    out = node(_state(market_report="orig", final_trade_decision="**Rating**: Buy"))

    assert out == {"validation_report": ""}
    llm.with_structured_output.assert_not_called()


@pytest.mark.unit
def test_signal_stable_after_final_decision_correction(monkeypatch):
    from tradingagents.agents.utils.rating import parse_rating

    monkeypatch.setattr(rv, "build_verified_market_snapshot", lambda s, d: "SNAPSHOT")
    original = "**Rating**: Buy\n\n某基金 值得买入。"
    corrected = "**Rating**: Buy\n\n航空航天ETF天弘 值得买入。"
    llm, _ = _structured_llm(
        invoke_return=CorrectedReport(
            corrected_text=corrected,
            corrections=[CorrectionItem(original="某基金", fixed="航空航天ETF天弘", reason="名称不符")],
        )
    )
    node = rv.create_report_validator(llm, enabled=True)
    out = node(_state(final_trade_decision=original))

    assert parse_rating(out["final_trade_decision"]) == parse_rating(original) == "Buy"
    assert "**Rating**: Buy" in out["final_trade_decision"]   # 评级词未被改动
    assert "航空航天ETF天弘" in out["final_trade_decision"]    # 名称已修正
    assert "某基金" not in out["final_trade_decision"]         # 旧名称已替换


@pytest.mark.unit
def test_structured_failure_keeps_original(monkeypatch):
    monkeypatch.setattr(rv, "build_verified_market_snapshot", lambda s, d: "SNAPSHOT")
    llm, _ = _structured_llm(invoke_side_effect=RuntimeError("malformed json"))
    node = rv.create_report_validator(llm, enabled=True)
    out = node(_state(market_report="orig"))

    assert "market_report" not in out
    assert "校验失败" in out["validation_report"]


@pytest.mark.unit
def test_structured_output_unsupported_marks_unverified(monkeypatch):
    monkeypatch.setattr(rv, "build_verified_market_snapshot", lambda s, d: "SNAPSHOT")
    llm = MagicMock()
    llm.with_structured_output.side_effect = NotImplementedError
    node = rv.create_report_validator(llm, enabled=True)
    out = node(_state(market_report="orig"))

    assert "market_report" not in out
    assert "未校验" in out["validation_report"]
