from unittest.mock import patch

import pytest

from tradingagents.llm_clients.health_check import HealthReport, ProbeResult, SlotReport


def _fake_report():
    return HealthReport(
        provider="ibm_ica",
        slots={
            "deep_think_llm": SlotReport(
                configured="claude-opus-4-8",
                selected="claude-opus-4-7",  # 模拟回退
                all_failed=False,
                candidates=[
                    ProbeResult("claude-opus-4-8", False, "RuntimeError: down", 12),
                    ProbeResult("claude-opus-4-7", True, None, 30),
                ],
            ),
            "quick_think_llm": SlotReport(
                configured="claude-haiku-4-5",
                selected="claude-haiku-4-5",
                all_failed=False,
                candidates=[ProbeResult("claude-haiku-4-5", True, None, 20)],
            ),
        },
        any_failed=False,
    )


@pytest.mark.unit
def test_run_model_health_check_writes_back_and_stores_report(monkeypatch):
    import api.main as main
    from tradingagents.default_config import DEFAULT_CONFIG

    # 用 setitem 预置并自动还原全局 DEFAULT_CONFIG
    monkeypatch.setitem(DEFAULT_CONFIG, "deep_think_llm", "claude-opus-4-8")
    monkeypatch.setitem(DEFAULT_CONFIG, "quick_think_llm", "claude-haiku-4-5")
    main.app.state.model_health = None

    with patch.object(main, "check_and_select", return_value=_fake_report()):
        main._run_model_health_check()

    assert DEFAULT_CONFIG["deep_think_llm"] == "claude-opus-4-7"  # 选型写回
    assert DEFAULT_CONFIG["quick_think_llm"] == "claude-haiku-4-5"
    assert main.app.state.model_health is not None
    assert main.app.state.model_health.provider == "ibm_ica"


@pytest.mark.unit
def test_run_model_health_check_all_failed_does_not_raise(monkeypatch):
    import api.main as main
    from tradingagents.default_config import DEFAULT_CONFIG

    monkeypatch.setitem(DEFAULT_CONFIG, "deep_think_llm", "claude-opus-4-8")
    monkeypatch.setitem(DEFAULT_CONFIG, "quick_think_llm", "claude-haiku-4-5")

    report = _fake_report()
    report.slots["deep_think_llm"].all_failed = True
    report.slots["deep_think_llm"].selected = "claude-opus-4-8"
    report.any_failed = True

    with patch.object(main, "check_and_select", return_value=report):
        main._run_model_health_check()  # 不抛即通过

    assert DEFAULT_CONFIG["deep_think_llm"] == "claude-opus-4-8"  # 全挂保留原值


@pytest.mark.unit
def test_run_model_health_check_swallows_internal_errors(monkeypatch):
    import api.main as main

    with patch.object(main, "check_and_select", side_effect=RuntimeError("boom")):
        main._run_model_health_check()  # 健康检查自身报错也不得冒泡
