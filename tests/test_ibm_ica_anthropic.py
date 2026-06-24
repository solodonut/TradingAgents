import json

import httpx
import pytest

from tradingagents.llm_clients.anthropic_client import IbmIcaAnthropicClient
from tradingagents.llm_clients.factory import create_llm_client


def _message_response(model: str) -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


@pytest.mark.unit
def test_factory_routes_ibm_ica_to_anthropic_client(monkeypatch):
    monkeypatch.setenv("IBM_ICA_API_KEY", "test-ica-key")
    client = create_llm_client("ibm_ica", "claude-haiku-4-5")
    assert isinstance(client, IbmIcaAnthropicClient)


@pytest.mark.unit
def test_ibm_ica_sends_anthropic_messages_request(monkeypatch):
    monkeypatch.setenv("IBM_ICA_API_KEY", "test-ica-key")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_message_response("claude-haiku-4-5"))

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    llm = create_llm_client("ibm_ica", "claude-haiku-4-5").get_llm()
    llm._client._client = http_client

    assert llm.invoke("ping").content == "ok"
    request = captured["request"]
    assert str(request.url) == "https://api.nextgen-beta.ica.ibm.com/ica/v1/messages"
    assert request.headers["x-api-key"] == "test-ica-key"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in request.headers
    assert captured["body"]["model"] == "claude-haiku-4-5"
    assert "messages" in captured["body"]


@pytest.mark.unit
def test_ibm_ica_base_url_env_override(monkeypatch):
    monkeypatch.setenv("IBM_ICA_API_KEY", "test-ica-key")
    monkeypatch.setenv("IBM_ICA_BASE_URL", "https://tenant.example/ica")
    llm = create_llm_client("ibm_ica", "claude-haiku-4-5").get_llm()
    assert str(llm.anthropic_api_url) == "https://tenant.example/ica"


@pytest.mark.unit
def test_ibm_ica_explicit_base_url_wins(monkeypatch):
    monkeypatch.setenv("IBM_ICA_API_KEY", "test-ica-key")
    monkeypatch.setenv("IBM_ICA_BASE_URL", "https://env.example/ica")
    llm = create_llm_client(
        "ibm_ica",
        "claude-haiku-4-5",
        base_url="https://explicit.example/ica",
    ).get_llm()
    assert str(llm.anthropic_api_url) == "https://explicit.example/ica"


@pytest.mark.unit
def test_ibm_ica_does_not_fall_back_to_anthropic_key(monkeypatch):
    monkeypatch.delenv("IBM_ICA_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "wrong-provider-key")
    with pytest.raises(ValueError, match="IBM_ICA_API_KEY"):
        create_llm_client("ibm_ica", "claude-haiku-4-5")
