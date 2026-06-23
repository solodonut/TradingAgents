from unittest.mock import MagicMock, patch

import pytest

from tradingagents.llm_clients.health_check import ProbeResult, probe_model


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
