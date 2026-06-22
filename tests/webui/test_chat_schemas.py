import pytest
from pydantic import ValidationError

from api.schemas import (
    ChatMessage,
    ChatRequest,
    ChatSession,
    ChatSessionCreate,
    PortfolioExtractResponse,
    PortfolioHolding,
    SessionProfile,
)


def test_portfolio_holding_only_ticker_required():
    h = PortfolioHolding(ticker="AAPL")
    assert h.ticker == "AAPL"
    assert h.shares is None
    assert h.action is None


def test_portfolio_holding_action_literal_rejects_bad_value():
    with pytest.raises(ValidationError):
        PortfolioHolding(ticker="AAPL", action="hodl")


def test_chat_message_role_literal():
    m = ChatMessage(
        message_id="m1",
        session_id="s1",
        role="assistant",
        content="hello",
        created_at="2026-06-17T00:00:00+00:00",
    )
    assert m.role == "assistant"
    assert m.tool_calls == []


def test_chat_session_create_run_id_optional():
    assert ChatSessionCreate().run_id is None
    assert ChatSessionCreate(run_id="r1").run_id == "r1"


def test_portfolio_extract_response_defaults():
    r = PortfolioExtractResponse(source="vision")
    assert r.holdings == []
    assert r.source == "vision"


def test_chat_request_message_required():
    with pytest.raises(ValidationError):
        ChatRequest()
    assert ChatRequest(message="hi").message == "hi"


def test_chat_session_shape():
    s = ChatSession(
        session_id="s1",
        run_id=None,
        title="AAPL chat",
        created_at="2026-06-17T00:00:00+00:00",
        updated_at="2026-06-17T00:00:00+00:00",
    )
    assert s.session_id == "s1"
    assert s.run_id is None


def test_session_profile_defaults_are_all_optional():
    profile = SessionProfile()
    assert profile.available_capital is None
    assert profile.capital_currency == "CNY"
    assert profile.risk_tolerance is None
    assert profile.max_single_position_pct is None
    assert profile.horizon is None
    assert profile.constraints is None
    assert profile.confirmed_at is None


def test_session_profile_accepts_full_values():
    profile = SessionProfile(
        available_capital=300000,
        capital_currency="USD",
        risk_tolerance="balanced",
        max_single_position_pct=25,
        horizon="medium",
        constraints="不碰白酒",
        confirmed_at="2026-06-22T00:00:00Z",
    )
    assert profile.available_capital == 300000
    assert profile.risk_tolerance == "balanced"
    assert profile.horizon == "medium"
