from unittest.mock import MagicMock, patch

import pytest

from tradingagents.llm_clients.health_check import (
    HealthReport,
    ProbeResult,
    SlotReport,
    check_and_select,
    probe_model,
)


@pytest.mark.unit
def test_probe_model_ok_when_invoke_succeeds():
    client = MagicMock()
    client.get_llm.return_value.invoke.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.health_check.create_llm_client",
        return_value=client,
    ):
        result = probe_model("ibm_ica", "claude-haiku-4-5", None)

    assert isinstance(result, ProbeResult)
    assert result.model == "claude-haiku-4-5"
    assert result.ok is True
    assert result.error is None
    assert result.latency_ms >= 0


@pytest.mark.unit
def test_probe_model_failure_captures_error_and_does_not_raise():
    with patch(
        "tradingagents.llm_clients.health_check.create_llm_client",
        side_effect=RuntimeError("boom"),
    ):
        result = probe_model("ibm_ica", "bad-model", None)

    assert result.ok is False
    assert result.model == "bad-model"
    assert "RuntimeError" in result.error
    assert "boom" in result.error


@pytest.mark.unit
def test_probe_model_failure_when_invoke_raises():
    client = MagicMock()
    client.get_llm.return_value.invoke.side_effect = ValueError("auth failed")
    with patch(
        "tradingagents.llm_clients.health_check.create_llm_client",
        return_value=client,
    ):
        result = probe_model("ibm_ica", "claude-haiku-4-5", None)

    assert result.ok is False
    assert "ValueError" in result.error


_ICA_CONFIG = {
    "llm_provider": "ibm_ica",
    "deep_think_llm": "claude-opus-4-8",
    "quick_think_llm": "claude-haiku-4-5",
    "backend_url": None,
}


def _factory_where(ok_models):
    """Return a create_llm_client replacement whose models in ok_models work."""

    def _make(provider, model, base_url=None, **kwargs):
        client = MagicMock()
        if model in ok_models:
            client.get_llm.return_value.invoke.return_value = MagicMock()
        else:
            client.get_llm.return_value.invoke.side_effect = RuntimeError(f"down: {model}")
        return client

    return _make


@pytest.mark.unit
def test_check_and_select_keeps_configured_when_it_works():
    # 所有候选都可用 -> 原配置优先，selected == configured
    all_ok = MagicMock()
    all_ok.get_llm.return_value.invoke.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.health_check.create_llm_client",
        return_value=all_ok,
    ):
        report = check_and_select(dict(_ICA_CONFIG))

    assert isinstance(report, HealthReport)
    assert report.provider == "ibm_ica"
    assert report.any_failed is False
    deep = report.slots["deep_think_llm"]
    quick = report.slots["quick_think_llm"]
    assert deep.selected == "claude-opus-4-8"
    assert quick.selected == "claude-haiku-4-5"
    # "全部测一遍"：候选含 configured + catalog 非 custom 项
    assert deep.candidates[0].model == "claude-opus-4-8"
    assert len(deep.candidates) == 5  # opus-4-8, opus-4-7, sonnet-4-6, gpt-5.4-gus, gemini-3.1-pro-preview
    assert len(quick.candidates) == 4  # haiku-4-5, sonnet-4-6, gpt-5.1-chat-gus, granite-4-h-small
    assert "custom" not in [c.model for c in deep.candidates]


@pytest.mark.unit
def test_check_and_select_falls_back_to_first_working_candidate():
    # 配置的 deep 模型挂，下一候选 opus-4-7 可用；quick 全程可用
    ok = {
        "claude-haiku-4-5",
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "gpt-5.1-chat-gus",
        "ibm/granite-4-h-small",
        "gpt-5.4-gus",
        "gemini-3.1-pro-preview",
    }  # 注意：不含 claude-opus-4-8
    with patch(
        "tradingagents.llm_clients.health_check.create_llm_client",
        side_effect=_factory_where(ok),
    ):
        report = check_and_select(dict(_ICA_CONFIG))

    deep = report.slots["deep_think_llm"]
    assert deep.configured == "claude-opus-4-8"
    assert deep.selected == "claude-opus-4-7"  # configured 之后第一个 ok
    assert deep.all_failed is False
    assert report.any_failed is False
    assert report.slots["quick_think_llm"].selected == "claude-haiku-4-5"


@pytest.mark.unit
def test_check_and_select_marks_all_failed_and_keeps_configured():
    # deep 槽位所有候选都挂；quick 正常
    quick_only = {
        "claude-haiku-4-5",
        "gpt-5.1-chat-gus",
        "ibm/granite-4-h-small",
    }
    with patch(
        "tradingagents.llm_clients.health_check.create_llm_client",
        side_effect=_factory_where(quick_only),
    ):
        report = check_and_select(dict(_ICA_CONFIG))

    deep = report.slots["deep_think_llm"]
    assert deep.all_failed is True
    assert deep.selected == "claude-opus-4-8"  # 保留原配置
    assert report.any_failed is True


@pytest.mark.unit
def test_check_and_select_provider_not_in_catalog_uses_only_configured():
    config = {
        "llm_provider": "openrouter",  # 不在 MODEL_OPTIONS
        "deep_think_llm": "some/deep-model",
        "quick_think_llm": "some/quick-model",
        "backend_url": None,
    }
    all_ok = MagicMock()
    all_ok.get_llm.return_value.invoke.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.health_check.create_llm_client",
        return_value=all_ok,
    ):
        report = check_and_select(config)

    deep = report.slots["deep_think_llm"]
    assert [c.model for c in deep.candidates] == ["some/deep-model"]
    assert deep.selected == "some/deep-model"
    assert isinstance(report.slots["quick_think_llm"], SlotReport)
