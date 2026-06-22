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
