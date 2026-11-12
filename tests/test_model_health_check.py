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
def test_check_and_select_probes_only_configured_models():
    # 只探测 .env 配置的模型，不再带 catalog 备选
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
    assert [c.model for c in deep.candidates] == ["claude-opus-4-8"]
    assert [c.model for c in quick.candidates] == ["claude-haiku-4-5"]
    assert deep.selected == "claude-opus-4-8"
    assert quick.selected == "claude-haiku-4-5"


@pytest.mark.unit
def test_check_and_select_does_not_fall_back_when_configured_fails():
    # 配置的 deep 模型挂：即使 catalog 里有可用模型也不切换，直接标记失败
    ok = {"claude-haiku-4-5", "claude-opus-4-7", "claude-sonnet-4-6"}
    with patch(
        "tradingagents.llm_clients.health_check.create_llm_client",
        side_effect=_factory_where(ok),
    ):
        report = check_and_select(dict(_ICA_CONFIG))

    deep = report.slots["deep_think_llm"]
    assert deep.selected == "claude-opus-4-8"  # 保留原配置
    assert deep.all_failed is True
    assert report.any_failed is True
    assert report.slots["quick_think_llm"].all_failed is False


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
