"""Tests for configurable LLM retry budget and request timeout.

A transient gateway failure (e.g. a 502 from the IBM ICA / Cloudflare front)
in any node's ``llm.invoke`` used to crash the whole multi-agent run, because
the SDK default retry budget (2) is too small to ride out a multi-second blip.
``llm_max_retries`` / ``llm_request_timeout`` are cross-provider knobs forwarded
to every chat client so the SDK absorbs transient 5xx/429/timeouts with backoff.
"""

import importlib

import pytest

from tradingagents.llm_clients.factory import create_llm_client


@pytest.mark.unit
class TestRetryForwarding:
    @pytest.mark.parametrize(
        "provider,model",
        [
            ("openai", "gpt-4.1"),
            ("anthropic", "claude-sonnet-4-6"),
            ("google", "gemini-2.5-flash"),
            ("deepseek", "deepseek-chat"),
        ],
    )
    def test_max_retries_reaches_client_when_set(self, provider, model):
        llm = create_llm_client(
            provider=provider, model=model, max_retries=6, api_key="placeholder"
        ).get_llm()
        assert llm.max_retries == 6

    def test_anthropic_default_budget_without_override(self):
        # Sanity: without forwarding, the Anthropic SDK budget is the small
        # default (2) — the gap this config closes.
        llm = create_llm_client(
            provider="anthropic", model="claude-sonnet-4-6", api_key="placeholder"
        ).get_llm()
        assert llm.max_retries == 2


@pytest.mark.unit
class TestRetryEnvOverlay:
    def test_env_sets_max_retries_as_int(self, monkeypatch):
        import tradingagents.default_config as dc
        monkeypatch.setenv("TRADINGAGENTS_LLM_MAX_RETRIES", "8")
        importlib.reload(dc)
        # Reference default is int 6, so env coercion yields an int.
        assert dc.DEFAULT_CONFIG["llm_max_retries"] == 8
        monkeypatch.delenv("TRADINGAGENTS_LLM_MAX_RETRIES", raising=False)
        importlib.reload(dc)

    def test_default_max_retries_is_six(self, monkeypatch):
        import tradingagents.default_config as dc
        monkeypatch.delenv("TRADINGAGENTS_LLM_MAX_RETRIES", raising=False)
        importlib.reload(dc)
        assert dc.DEFAULT_CONFIG["llm_max_retries"] == 6

    def test_default_request_timeout_is_none(self, monkeypatch):
        import tradingagents.default_config as dc
        monkeypatch.delenv("TRADINGAGENTS_LLM_REQUEST_TIMEOUT", raising=False)
        importlib.reload(dc)
        assert dc.DEFAULT_CONFIG["llm_request_timeout"] is None


@pytest.mark.unit
class TestProviderKwargsRetry:
    """_get_provider_kwargs forwards/coerces retry budget and timeout."""

    def _kwargs_for(self, **overrides):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.config = {"llm_provider": "anthropic", **overrides}
        return TradingAgentsGraph._get_provider_kwargs(graph)

    def test_max_retries_int_passthrough(self):
        assert self._kwargs_for(llm_max_retries=6)["max_retries"] == 6

    def test_max_retries_string_coerced(self):
        assert self._kwargs_for(llm_max_retries="8")["max_retries"] == 8

    def test_max_retries_none_omitted(self):
        assert "max_retries" not in self._kwargs_for(llm_max_retries=None)

    def test_timeout_float_string_coerced(self):
        assert self._kwargs_for(llm_request_timeout="120")["timeout"] == 120.0

    def test_timeout_none_omitted(self):
        assert "timeout" not in self._kwargs_for(llm_request_timeout=None)

    def test_timeout_empty_string_omitted(self):
        assert "timeout" not in self._kwargs_for(llm_request_timeout="")
