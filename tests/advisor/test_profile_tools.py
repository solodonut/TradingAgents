import json

import pytest

from tradingagents.advisor.profile_tools import create_profile_tools


def _tools(profile: dict | None = None):
    state = {"profile": profile or {}}
    tools = create_profile_tools(load_profile=lambda: state["profile"])
    return {t.name: t for t in tools}, state


def test_propose_session_facts_returns_only_provided_fields():
    tools, _ = _tools()
    out = tools["propose_session_facts"].invoke(
        {"available_capital": 300000, "capital_currency": "CNY"}
    )
    payload = json.loads(out)
    assert payload["proposal"] == {
        "available_capital": 300000,
        "capital_currency": "CNY",
    }
    assert "确认" in payload["instruction"]


def test_propose_session_facts_rejects_negative_capital():
    tools, _ = _tools()
    with pytest.raises(ValueError):
        tools["propose_session_facts"].invoke({"available_capital": -1})


def test_propose_session_facts_rejects_bad_enum_and_pct():
    tools, _ = _tools()
    with pytest.raises(ValueError):
        tools["propose_session_facts"].invoke({"risk_tolerance": "wild"})
    with pytest.raises(ValueError):
        tools["propose_session_facts"].invoke({"max_single_position_pct": 150})


def test_propose_session_facts_requires_at_least_one_field():
    tools, _ = _tools()
    with pytest.raises(ValueError):
        tools["propose_session_facts"].invoke({})


def test_compute_position_sizing_needs_capital_when_unset():
    tools, _ = _tools(profile={})
    out = tools["compute_position_sizing"].invoke(
        {"ticker": "AAPL", "price": 200, "target_weight_pct": 10}
    )
    assert out.startswith("NEED_CONFIRMATION:")


def test_compute_position_sizing_needs_capital_when_zero():
    tools, _ = _tools(profile={"available_capital": 0})
    out = tools["compute_position_sizing"].invoke(
        {"ticker": "AAPL", "price": 200, "target_weight_pct": 10}
    )
    assert out.startswith("NEED_CONFIRMATION:")


def test_compute_position_sizing_by_weight():
    tools, _ = _tools(
        profile={"available_capital": 300000, "capital_currency": "CNY",
                 "max_single_position_pct": 25}
    )
    out = tools["compute_position_sizing"].invoke(
        {"ticker": "AAPL", "price": 200, "target_weight_pct": 10}
    )
    payload = json.loads(out)
    assert payload["amount"] == 30000
    assert payload["shares"] == 150
    assert payload["exceeds_max"] is False


def test_compute_position_sizing_flags_exceeding_max():
    tools, _ = _tools(
        profile={"available_capital": 300000, "max_single_position_pct": 25}
    )
    out = tools["compute_position_sizing"].invoke(
        {"ticker": "AAPL", "price": 100, "target_weight_pct": 40}
    )
    assert json.loads(out)["exceeds_max"] is True


def test_compute_position_sizing_by_amount_derives_weight():
    tools, _ = _tools(profile={"available_capital": 200000})
    out = tools["compute_position_sizing"].invoke(
        {"ticker": "AAPL", "price": 50, "target_amount": 50000}
    )
    payload = json.loads(out)
    assert payload["target_weight_pct"] == 25.0
    assert payload["shares"] == 1000


def test_compute_position_sizing_requires_exactly_one_target():
    tools, _ = _tools(profile={"available_capital": 200000})
    with pytest.raises(ValueError):
        tools["compute_position_sizing"].invoke({"ticker": "A", "price": 10})
    with pytest.raises(ValueError):
        tools["compute_position_sizing"].invoke(
            {"ticker": "A", "price": 10, "target_weight_pct": 5, "target_amount": 100}
        )


def test_compute_position_sizing_rejects_nonpositive_price():
    tools, _ = _tools(profile={"available_capital": 200000})
    with pytest.raises(ValueError):
        tools["compute_position_sizing"].invoke(
            {"ticker": "A", "price": 0, "target_weight_pct": 5}
        )
