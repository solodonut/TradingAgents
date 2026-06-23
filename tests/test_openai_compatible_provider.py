"""Generic OpenAI-compatible provider (vLLM / LM Studio / llama.cpp / relays).

Verifies the user-supplied base_url is required and honored, the key is optional
(keyless local default), Chat Completions (not the Responses API) is used, any
model name is accepted, and the env backend URL precedence (#978).
"""

import pytest
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from tradingagents.llm_clients.api_key_env import get_api_key_env
from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.llm_clients.openai_client import NormalizedChatOpenAI
from tradingagents.llm_clients.validators import validate_model

# Note: assert by class NAME, not isinstance — other tests reload the
# openai_client module, which would otherwise create a second class identity.


@pytest.mark.unit
def test_factory_routes_to_openai_client():
    client = create_llm_client(
        provider="openai_compatible", model="my-model", base_url="http://localhost:8000/v1"
    )
    assert type(client).__name__ == "OpenAIClient"


@pytest.mark.unit
def test_base_url_required(monkeypatch):
    monkeypatch.delenv("OPENAI_COMPATIBLE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="requires a base_url"):
        create_llm_client(provider="openai_compatible", model="m").get_llm()


@pytest.mark.unit
def test_keyless_local_uses_placeholder_and_chat_completions(monkeypatch):
    monkeypatch.delenv("OPENAI_COMPATIBLE_API_KEY", raising=False)
    llm = create_llm_client(
        provider="openai_compatible", model="qwen2.5", base_url="http://localhost:8000/v1"
    ).get_llm()
    assert type(llm).__name__ == "NormalizedChatOpenAI"
    assert str(llm.openai_api_base) == "http://localhost:8000/v1"
    # keyless local servers: a placeholder key is sent
    key = llm.openai_api_key.get_secret_value() if hasattr(llm.openai_api_key, "get_secret_value") else llm.openai_api_key
    assert key == "EMPTY"
    # must use Chat Completions, not OpenAI's Responses API
    assert getattr(llm, "use_responses_api", False) in (False, None)


@pytest.mark.unit
def test_optional_key_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "sk-relay-123")
    llm = create_llm_client(
        provider="openai_compatible", model="m", base_url="https://relay.example/v1"
    ).get_llm()
    key = llm.openai_api_key.get_secret_value() if hasattr(llm.openai_api_key, "get_secret_value") else llm.openai_api_key
    assert key == "sk-relay-123"


@pytest.mark.unit
def test_any_model_accepted_no_forced_key():
    assert validate_model("openai_compatible", "literally-anything") is True
    # The key env exists (read for keyed relays) but the provider is marked
    # key-optional, so the CLI never forces a prompt and keyless servers work.
    assert get_api_key_env("openai_compatible") == "OPENAI_COMPATIBLE_API_KEY"
    from tradingagents.llm_clients.openai_client import OPENAI_COMPATIBLE_PROVIDERS
    assert OPENAI_COMPATIBLE_PROVIDERS["openai_compatible"].key_optional is True


@pytest.mark.unit
def test_normalized_client_retries_one_empty_provider_response(monkeypatch):
    attempts = 0

    def invoke_once_empty_then_succeed(self, input, config=None, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise AttributeError("'NoneType' object has no attribute 'model_dump'")
        return AIMessage(content="OK")

    monkeypatch.setattr(ChatOpenAI, "invoke", invoke_once_empty_then_succeed)
    llm = NormalizedChatOpenAI(model="test-model", api_key="test-key")

    result = llm.invoke("hello")

    assert result.content == "OK"
    assert attempts == 2


@pytest.mark.unit
def test_ica_model_not_found_translates_to_clear_error(monkeypatch):
    # IBM ICA rejects an unknown model ID with an opaque
    # 400 - {'detail': 'Model not found'}. The ibm_ica client should translate
    # that into a clear error naming the rejected model and listing what the
    # gateway currently serves.
    from tradingagents.llm_clients import openai_client as oc

    def raise_model_not_found(self, input, config=None, **kwargs):
        raise Exception("Error code: 400 - {'detail': 'Model not found'}")

    monkeypatch.setattr(ChatOpenAI, "invoke", raise_model_not_found)
    monkeypatch.setattr(
        oc, "_fetch_ica_models", lambda base_url, api_key: ["claude-haiku-4-5", "claude-opus-4-8"]
    )
    llm = oc.IbmIcaChatOpenAI(
        model="claude-haiku-4.5",
        api_key="test-key",
        base_url="https://api.nextgen-beta.ica.ibm.com/ica/v1/chat-models",
    )

    with pytest.raises(ValueError) as excinfo:
        llm.invoke("hi")

    msg = str(excinfo.value)
    assert "claude-haiku-4.5" in msg  # the rejected model is named
    assert "claude-opus-4-8" in msg   # available models are listed


@pytest.mark.unit
def test_ica_other_errors_propagate_unchanged(monkeypatch):
    from tradingagents.llm_clients import openai_client as oc

    def raise_other(self, input, config=None, **kwargs):
        raise RuntimeError("some other failure")

    monkeypatch.setattr(ChatOpenAI, "invoke", raise_other)
    llm = oc.IbmIcaChatOpenAI(
        model="claude-haiku-4-5", api_key="test-key", base_url="https://x/ica/v1/chat-models"
    )

    with pytest.raises(RuntimeError, match="some other failure"):
        llm.invoke("hi")


@pytest.mark.unit
def test_ica_guardrail_failure_translates_to_clear_error(monkeypatch):
    # ICA's guardrail subsystem fails with an opaque
    # 500 - Custom code guardrail execution failed: Model not available - E001
    # when the guardrail backend for a model family is down. This is a
    # gateway-side outage (the model is still in the catalog), so it must be
    # translated differently from the 400 "Model not found" case — and it must
    # NOT trigger a /models catalog fetch.
    from tradingagents.llm_clients import openai_client as oc

    def raise_guardrail(self, input, config=None, **kwargs):
        raise Exception(
            "Error code: 500 - {'error': {'message': 'Custom code guardrail "
            "execution failed: Model not available - E001'}}"
        )

    def fail_if_called(base_url, api_key):
        raise AssertionError("_fetch_ica_models must not run on a guardrail 500")

    monkeypatch.setattr(ChatOpenAI, "invoke", raise_guardrail)
    monkeypatch.setattr(oc, "_fetch_ica_models", fail_if_called)
    llm = oc.IbmIcaChatOpenAI(
        model="claude-opus-4-8", api_key="test-key", base_url="https://x/ica/v1/chat-models"
    )

    with pytest.raises(ValueError) as excinfo:
        llm.invoke("hi")

    msg = str(excinfo.value)
    assert "claude-opus-4-8" in msg       # the affected model is named
    assert "guardrail" in msg.lower()     # framed as a gateway-side outage
    assert "E001" in msg


@pytest.mark.unit
def test_env_backend_url_precedence():
    # #978: explicit env URL wins over the menu/default regardless of provider source.
    from cli.utils import resolve_backend_url
    assert resolve_backend_url("openai", "https://api.openai.com/v1", env_url="http://proxy/v1") == "http://proxy/v1"
    assert resolve_backend_url("openai", "https://api.openai.com/v1", env_url=None) == "https://api.openai.com/v1"
    assert resolve_backend_url("deepseek", None, None) == "https://api.deepseek.com"
