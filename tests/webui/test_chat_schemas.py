import pytest
from pydantic import ValidationError

from api.schemas import (
    ChatMessage,
    ChatRequest,
    ChatSession,
    ChatSessionCreate,
    PortfolioExtractResponse,
    PortfolioHolding,
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
