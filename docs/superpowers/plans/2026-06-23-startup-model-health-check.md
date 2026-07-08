# 启动时模型健康检查与自动选型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 服务启动时探测当前 provider 的候选模型，全部测一遍并报告，为 `deep_think_llm` / `quick_think_llm` 各选一个可用模型写回配置，原配置优先、全挂不阻断启动。

**Architecture:** 新增无框架依赖的 `tradingagents/llm_clients/health_check.py`，对外暴露 `probe_model()`（探测单个模型）与 `check_and_select()`（按槽位测全部候选并选型，返回 `HealthReport`，不改全局配置）。WebUI 在 `@app.on_event("startup")` 调用它、把选型写回 `DEFAULT_CONFIG`、把报告存到 `app.state.model_health`，并用环境变量开关以便测试关闭。

**Tech Stack:** Python ≥3.10、LangChain（`langchain_core.messages.HumanMessage`、`.invoke`）、FastAPI startup 事件、pytest + `unittest.mock`。

## Global Constraints

- Python ≥ 3.10（用了 `X | None` 联合语法）。
- 所有 Python/pytest 命令用项目 venv：`.venv/bin/python`、`.venv/bin/python -m pytest`。
- LLM 客户端实例化只走 `tradingagents/llm_clients/factory.py::create_llm_client`；模型清单只来自 `tradingagents/llm_clients/model_catalog.py::MODEL_OPTIONS`。
- 模块必须 import-safe：仅 import 它不得需要任何 API key、不得发网络请求。
- 收尾手动验证：`ruff check .` 与 `.venv/bin/python -m pytest -m "not integration"`。
- 提交用 Conventional Commits（`feat(...)` / `test(...)`），并维护 `CHANGELOG.md`。**仅在用户明确要求时才提交/推送**——除非用户已要求，否则各任务的 commit 步骤先不要执行，把改动留在工作区。

---

### Task 1: `probe_model` 探测单个模型 + `ProbeResult`

**Files:**
- Create: `tradingagents/llm_clients/health_check.py`
- Test: `tests/test_model_health_check.py`

**Interfaces:**
- Consumes: `tradingagents.llm_clients.factory.create_llm_client(provider, model, base_url, **kwargs)`（返回带 `.get_llm()` 的客户端，`get_llm()` 返回带 `.invoke(messages)` 的 LangChain 模型）。
- Produces:
  - `ProbeResult(model: str, ok: bool, error: str | None, latency_ms: int)`（dataclass）。
  - `probe_model(provider: str, model: str, base_url: str | None = None) -> ProbeResult`。

> 设计说明：spec 提到的 `timeout` 参数本次不实现——各 provider 客户端没有统一的「单次调用超时」注入口，强行加会变成未使用参数（占位坑）。探测依赖各客户端默认超时；待以后需要时再统一加。

- [ ] **Step 1: Write the failing test**

写 `tests/test_model_health_check.py`：

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_model_health_check.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tradingagents.llm_clients.health_check'`（或 ImportError）。

- [ ] **Step 3: Write minimal implementation**

创建 `tradingagents/llm_clients/health_check.py`：

```python
"""Startup-time LLM health check and automatic model selection.

Probes the configured provider's candidate models so the service can pick a
working model for each slot before the first real analysis runs. Framework-free
and import-safe: importing this module must not require an API key or perform
any network request.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from langchain_core.messages import HumanMessage

from .factory import create_llm_client

_PING = [HumanMessage(content="ping")]
_MAX_ERROR_LEN = 500


@dataclass
class ProbeResult:
    model: str
    ok: bool
    error: str | None
    latency_ms: int


def probe_model(provider: str, model: str, base_url: str | None = None) -> ProbeResult:
    """Probe one model with a minimal request. Never raises.

    A model is considered usable if a minimal ``invoke`` returns without
    raising. Any exception (build error, auth, network, bad model) yields
    ``ok=False`` with a short error string.
    """
    start = time.monotonic()
    try:
        client = create_llm_client(provider=provider, model=model, base_url=base_url)
        client.get_llm().invoke(_PING)
    except Exception as exc:  # noqa: BLE001 - any failure means "unusable"
        elapsed = int((time.monotonic() - start) * 1000)
        message = f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_LEN]
        return ProbeResult(model=model, ok=False, error=message, latency_ms=elapsed)
    elapsed = int((time.monotonic() - start) * 1000)
    return ProbeResult(model=model, ok=True, error=None, latency_ms=elapsed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_model_health_check.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit（仅当用户已要求提交时执行，否则跳过）**

```bash
git add tradingagents/llm_clients/health_check.py tests/test_model_health_check.py
git commit -m "feat(llm): add probe_model for startup health check"
```

---

### Task 2: `check_and_select` 按槽位测全部候选并选型

**Files:**
- Modify: `tradingagents/llm_clients/health_check.py`
- Test: `tests/test_model_health_check.py`（追加）

**Interfaces:**
- Consumes: `tradingagents.llm_clients.model_catalog.MODEL_OPTIONS`（`dict[provider][mode] -> list[(label, value)]`；`value == "custom"` 是占位项，需跳过）；上一任务的 `probe_model` / `ProbeResult`。
- Produces:
  - `SlotReport(configured: str, selected: str, all_failed: bool, candidates: list[ProbeResult])`。
  - `HealthReport(provider: str, slots: dict[str, SlotReport], any_failed: bool)`，`slots` 的 key 为 `"deep_think_llm"` / `"quick_think_llm"`。
  - `check_and_select(config: dict) -> HealthReport`。读取 `config["llm_provider"]`、`config["deep_think_llm"]`、`config["quick_think_llm"]`、`config.get("backend_url")`。**不修改 `config`。**

- [ ] **Step 1: Write the failing test**

在 `tests/test_model_health_check.py` 追加：

```python
from unittest.mock import MagicMock, patch  # 已在文件顶部，勿重复导入

from tradingagents.llm_clients.health_check import (  # 追加到已有 import
    HealthReport,
    SlotReport,
    check_and_select,
)

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
        "claude-sonnet-4-6",
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_model_health_check.py -v`
Expected: FAIL — `ImportError: cannot import name 'check_and_select'`（及 `HealthReport`/`SlotReport`）。

- [ ] **Step 3: Write minimal implementation**

在 `health_check.py` 顶部 import 区追加：

```python
from .model_catalog import MODEL_OPTIONS
```

在 `ProbeResult` 之后追加 dataclass 与逻辑：

```python
# Slots to check, mapped to the model_catalog mode used for their candidates.
_SLOT_MODES = {
    "deep_think_llm": "deep",
    "quick_think_llm": "quick",
}


@dataclass
class SlotReport:
    configured: str
    selected: str
    all_failed: bool
    candidates: list[ProbeResult]


@dataclass
class HealthReport:
    provider: str
    slots: dict[str, SlotReport]
    any_failed: bool


def _candidates_for(provider: str, configured: str, mode: str) -> list[str]:
    """Configured model first, then this provider's catalog candidates.

    Drops the ``"custom"`` placeholder and de-duplicates. Providers absent from
    the catalog (e.g. openrouter) yield just the configured model.
    """
    candidates = [configured]
    options = MODEL_OPTIONS.get(provider.lower(), {})
    for _label, value in options.get(mode, []):
        if value == "custom":
            continue
        if value not in candidates:
            candidates.append(value)
    return candidates


def check_and_select(config: dict) -> HealthReport:
    """Probe every candidate per slot and pick a working model.

    Selection is configured-first: keep the configured model if it works,
    otherwise take the first working candidate; if none work, keep the
    configured value and mark the slot ``all_failed``. Does not mutate config.
    """
    provider = config["llm_provider"]
    base_url = config.get("backend_url")
    slots: dict[str, SlotReport] = {}
    any_failed = False

    for slot, mode in _SLOT_MODES.items():
        configured = config[slot]
        candidates = _candidates_for(provider, configured, mode)
        results = [probe_model(provider, model, base_url) for model in candidates]

        if results[0].ok:  # configured is always first
            selected, all_failed = configured, False
        else:
            first_ok = next((r.model for r in results if r.ok), None)
            if first_ok is not None:
                selected, all_failed = first_ok, False
            else:
                selected, all_failed = configured, True

        any_failed = any_failed or all_failed
        slots[slot] = SlotReport(
            configured=configured,
            selected=selected,
            all_failed=all_failed,
            candidates=results,
        )

    return HealthReport(provider=provider, slots=slots, any_failed=any_failed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_model_health_check.py -v`
Expected: PASS（全部用例通过）。

- [ ] **Step 5: Commit（仅当用户已要求提交时执行，否则跳过）**

```bash
git add tradingagents/llm_clients/health_check.py tests/test_model_health_check.py
git commit -m "feat(llm): add check_and_select for per-slot model health check"
```

---

### Task 3: WebUI 启动接线 + 环境开关 + 测试关闭

**Files:**
- Modify: `api/main.py`
- Modify: `tests/conftest.py`（autouse 关闭启动检查，避免全套测试发真实网络）
- Test: `tests/webui/test_model_health_startup.py`

**Interfaces:**
- Consumes: `tradingagents.llm_clients.health_check.check_and_select`、`tradingagents.default_config.DEFAULT_CONFIG`、FastAPI `app.state`。
- Produces:
  - `api.main._run_model_health_check() -> None`：调 `check_and_select(DEFAULT_CONFIG)`，把每槽位 `selected` 写回 `DEFAULT_CONFIG`，日志输出报告，设 `app.state.model_health`；`any_failed` 时记 error 但不抛。
  - 环境开关 `TRADINGAGENTS_STARTUP_MODEL_CHECK`（默认开；值为 `0/false/no/off` 关闭）。
  - `app.state.model_health`（默认 `None`）。

- [ ] **Step 1: Write the failing test**

新建 `tests/webui/test_model_health_startup.py`：

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/webui/test_model_health_startup.py -v`
Expected: FAIL — `AttributeError: module 'api.main' has no attribute '_run_model_health_check'`（或 `check_and_select`）。

- [ ] **Step 3: Write minimal implementation**

在 `api/main.py` 顶部 import 区追加（紧跟现有 import）：

```python
import logging
import os
```

并在 `from tradingagents.default_config import DEFAULT_CONFIG` 之后追加：

```python
from tradingagents.llm_clients.health_check import check_and_select
```

在 `app.state.chat_llm_factory = None` 那一组初始化后追加：

```python
app.state.model_health = None  # set by the startup health check; tests may inject

logger = logging.getLogger(__name__)


def _startup_model_check_enabled() -> bool:
    return os.getenv("TRADINGAGENTS_STARTUP_MODEL_CHECK", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _run_model_health_check() -> None:
    """Probe configured models, write working ones back to DEFAULT_CONFIG.

    Never raises: a failing or buggy health check must not block startup.
    """
    try:
        report = check_and_select(DEFAULT_CONFIG)
    except Exception:  # noqa: BLE001 - health check must never crash startup
        logger.exception("model-health: health check failed; keeping configured models")
        return

    for slot, slot_report in report.slots.items():
        DEFAULT_CONFIG[slot] = slot_report.selected
        for candidate in slot_report.candidates:
            logger.info(
                "model-health %s candidate=%s ok=%s latency=%dms%s",
                slot,
                candidate.model,
                candidate.ok,
                candidate.latency_ms,
                f" error={candidate.error}" if candidate.error else "",
            )
        if slot_report.configured != slot_report.selected:
            logger.warning(
                "model-health %s switched %s -> %s",
                slot,
                slot_report.configured,
                slot_report.selected,
            )

    app.state.model_health = report

    if report.any_failed:
        failed = [slot for slot, sr in report.slots.items() if sr.all_failed]
        logger.error(
            "model-health: no working model for slots %s on provider %s; keeping configured values",
            failed,
            report.provider,
        )
```

在现有 `@app.on_event("startup")` 的 `_wire_graph_factory` 函数体末尾追加调用：

```python
    if _startup_model_check_enabled():
        _run_model_health_check()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/webui/test_model_health_startup.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 关闭测试期的启动检查（防止整套测试发真实网络）**

在 `tests/conftest.py` 现有 `_dummy_api_keys` autouse fixture 之后追加一个 autouse fixture：

```python
@pytest.fixture(autouse=True)
def _disable_startup_model_check(monkeypatch):
    """WebUI startup probes real models; force it off for the whole suite."""
    monkeypatch.setenv("TRADINGAGENTS_STARTUP_MODEL_CHECK", "0")
```

- [ ] **Step 6: 跑 webui smoke + 全量回归确认未破坏启动**

Run: `.venv/bin/python -m pytest tests/webui/test_smoke.py tests/webui/test_model_health_startup.py -v`
Expected: PASS（startup 因开关关闭而跳过健康检查，smoke 仍通过）。

Run: `.venv/bin/python -m pytest -m "not integration" -q`
Expected: 全绿，无新增失败。

- [ ] **Step 7: Lint + CHANGELOG**

Run: `.venv/bin/ruff check .`
Expected: 无新增告警。

在 `CHANGELOG.md` 的 `Unreleased`（若无则新建）`Added` 下加一行：

```markdown
- 服务启动时对当前 provider 的候选模型做健康检查，自动为 deep/quick 槽位选用可用模型（原配置优先，全挂不阻断启动）。可用 `TRADINGAGENTS_STARTUP_MODEL_CHECK=0` 关闭。
```

- [ ] **Step 8: Commit（仅当用户已要求提交时执行，否则跳过）**

```bash
git add api/main.py tests/conftest.py tests/webui/test_model_health_startup.py CHANGELOG.md
git commit -m "feat(api): run model health check on WebUI startup"
```

---

## Self-Review

**Spec coverage:**
- 独立可复用模块 → Task 1+2（`health_check.py`，无框架依赖）。✅
- 同 provider 内换模型 → `_candidates_for` 只取当前 provider 的 catalog（Task 2）。✅
- 全部测一遍并报告 → `check_and_select` 对每个候选都 `probe_model` 并存入 `candidates`（Task 2，含计数断言）。✅
- 原配置优先 → `results[0].ok` 优先分支（Task 2，`test_..._keeps_configured`）。✅
- 全挂不阻断启动 → `all_failed`/`any_failed` + Task 3 startup 不抛、env 开关、try/except。✅
- 日志 + 存 app.state → Task 3 `_run_model_health_check`（logger + `app.state.model_health`）。✅
- 只接 WebUI、不切 provider → Task 3 仅改 `api/main.py`；候选不跨 provider。✅

**Placeholder scan:** Task 2 第一个测试里特意标注并要求删除的无效 `with patch(... if False ...)` 块是唯一"伪占位"，已用注释明确指示删除；其余步骤均含完整代码与命令。无 TBD/TODO。

**Type consistency:** `ProbeResult` / `SlotReport` / `HealthReport` 字段在 Task 1/2/3 一致；`check_and_select(config)` 签名、`slots` 的 key（`"deep_think_llm"`/`"quick_think_llm"`）在测试与实现、Task 2 与 Task 3 间一致；`_run_model_health_check`、`check_and_select` 名称在 import、patch、调用处一致。
