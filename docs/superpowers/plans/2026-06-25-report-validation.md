# 报告校验与自动修正节点 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在交易决策流水线末尾新增一个图节点，对所有报告文本中的**标的名称**与**可验证市场数字**做事实校对，发现不一致时自动修正原文，并产出一份校验报告。

**Architecture:** 新增 `tradingagents/graph/report_validator.py`，提供 `create_report_validator(llm, enabled)` 工厂，返回一个 LangGraph 节点。节点确定性地从 `instrument_context`（标的身份）与 `build_verified_market_snapshot`（市场数字）取得"标准答案"，对 7 个报告字段各跑一次受严格约束的结构化 LLM 校对，把修正后的文本写回 state，并汇总到新字段 `validation_report`。节点接在 `Portfolio Manager → Report Validator → END`。

**Tech Stack:** Python 3.10+、LangGraph `StateGraph`、LangChain `with_structured_output`、Pydantic、pytest（`unit` marker）。

## Global Constraints

- Python **>= 3.10**（用 `X | None` union 语法）。
- 跑任何 Python/pytest 命令一律用项目 venv：`.venv/bin/python -m pytest ...`、`.venv/bin/ruff check .`。不要用裸 `python3`/`pytest`。
- **修正范围严格锁定**：只允许修正错误的标的名称和可验证市场数字（价格/OHLCV/技术指标值），**禁止改动任何分析、观点、结论、措辞、语气或结构**，不新增/删除内容、不翻译、不重写句子。
- 数据访问绝不直接调 yfinance/AKShare；市场数字只经 `build_verified_market_snapshot`。校验失败/数据缺失绝不抛异常或编造，按"未校验/校验失败"标注并保留原文。
- 提交遵循 Conventional Commits（`feat(graph):` 等），并同步 `CHANGELOG.md`（Keep a Changelog）。**仅在用户明确要求时才提交/推送**——本计划每个 Task 的"Commit"步骤在 subagent 执行时按需进行，最终是否 push 由用户决定。
- 收尾手动验证：`.venv/bin/ruff check .` 与 `.venv/bin/python -m pytest -m "not integration"` 必须通过（无 CI 兜底）。

---

### Task 1: 脚手架 — 校验 schema、state 字段、配置开关

**Files:**
- Modify: `tradingagents/agents/schemas.py`（文件末尾追加，当前 229 行）
- Modify: `tradingagents/agents/utils/agent_states.py:76`（在 `past_context` 行后追加字段）
- Modify: `tradingagents/default_config.py:24`（`_ENV_OVERRIDES` 末尾加一行）和 `:95`（`checkpoint_enabled` 行后加默认值）
- Test: `tests/test_report_validation_scaffold.py`（新建）

**Interfaces:**
- Produces:
  - `CorrectionItem(BaseModel)`：字段 `original: str`、`fixed: str`、`reason: str`。
  - `CorrectedReport(BaseModel)`：字段 `corrected_text: str`、`corrections: list[CorrectionItem]`（默认空列表）。
  - `AgentState["validation_report"]: str`。
  - `DEFAULT_CONFIG["report_validation_enabled"]: bool`（默认 `True`），可被 `TRADINGAGENTS_REPORT_VALIDATION_ENABLED` 覆盖。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_report_validation_scaffold.py`：

```python
"""Scaffolding for the report validation node: schemas, state field, config flag."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.unit
def test_corrected_report_schema_defaults():
    from tradingagents.agents.schemas import CorrectedReport

    report = CorrectedReport(corrected_text="原样文本")
    assert report.corrected_text == "原样文本"
    assert report.corrections == []


@pytest.mark.unit
def test_correction_item_fields():
    from tradingagents.agents.schemas import CorrectionItem

    item = CorrectionItem(original="某基金", fixed="航空航天ETF天弘", reason="名称与权威身份不符")
    assert item.original == "某基金"
    assert item.fixed == "航空航天ETF天弘"
    assert item.reason


@pytest.mark.unit
def test_agent_state_has_validation_report():
    from tradingagents.agents.utils.agent_states import AgentState

    assert "validation_report" in AgentState.__annotations__


@pytest.mark.unit
def test_config_default_enables_validation():
    from tradingagents.default_config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["report_validation_enabled"] is True


@pytest.mark.unit
def test_env_override_disables_validation(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_REPORT_VALIDATION_ENABLED", "false")
    import tradingagents.default_config as dc

    reloaded = importlib.reload(dc)
    try:
        assert reloaded.DEFAULT_CONFIG["report_validation_enabled"] is False
    finally:
        monkeypatch.delenv("TRADINGAGENTS_REPORT_VALIDATION_ENABLED", raising=False)
        importlib.reload(dc)  # restore module global for later tests
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_report_validation_scaffold.py -v`
Expected: FAIL（`ImportError: cannot import name 'CorrectedReport'` / `KeyError: 'report_validation_enabled'`）

- [ ] **Step 3: 加 schemas**

在 `tradingagents/agents/schemas.py` 文件**末尾**追加（紧接现有第 229 行之后）：

```python


# ---------------------------------------------------------------------------
# Report Validator
# ---------------------------------------------------------------------------


class CorrectionItem(BaseModel):
    """A single fact-level fix the report validator applied."""

    original: str = Field(description="原文中错误的标的名称或可验证数字片段（逐字摘录）。")
    fixed: str = Field(description="修正后的正确值，取自权威身份或权威市场数据快照。")
    reason: str = Field(description="为什么原值是错的——与哪个权威来源不符。")


class CorrectedReport(BaseModel):
    """A report text after fact-level correction, plus the list of fixes made."""

    corrected_text: str = Field(
        description=(
            "修正后的完整报告文本。只允许改动错误的标的名称和可验证数字；"
            "禁止改动分析、观点、结论、措辞或结构。若无任何错误，必须与原文逐字相同。"
        ),
    )
    corrections: list[CorrectionItem] = Field(
        default_factory=list,
        description="本次所做的修正清单；没有修正时为空列表。",
    )
```

- [ ] **Step 4: 加 state 字段**

在 `tradingagents/agents/utils/agent_states.py` 的 `AgentState` 里，`past_context`（第 76 行）之后追加：

```python
    validation_report: Annotated[str, "Report-validator consistency check: name/number fixes applied after the final decision"]
```

- [ ] **Step 5: 加配置开关**

在 `tradingagents/default_config.py` 的 `_ENV_OVERRIDES`（第 24 行 `}` 之前）追加一行：

```python
    "TRADINGAGENTS_REPORT_VALIDATION_ENABLED": "report_validation_enabled",
```

并在 `checkpoint_enabled` 默认值（第 95 行 `"checkpoint_enabled": False,`）之后追加：

```python
    # Post-decision report validation: when True, a final graph node fact-checks
    # every report's instrument name and verifiable market numbers against the
    # resolved identity + verified snapshot, auto-correcting mismatches and
    # writing a summary to ``validation_report``. Override with
    # TRADINGAGENTS_REPORT_VALIDATION_ENABLED.
    "report_validation_enabled": True,
```

- [ ] **Step 6: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_report_validation_scaffold.py -v`
Expected: PASS（5 passed）

- [ ] **Step 7: Commit**

```bash
git add tradingagents/agents/schemas.py tradingagents/agents/utils/agent_states.py tradingagents/default_config.py tests/test_report_validation_scaffold.py
git commit -m "feat(graph): add report-validation schemas, state field, config flag"
```

---

### Task 2: 校验节点 `report_validator.py`

**Files:**
- Create: `tradingagents/graph/report_validator.py`
- Test: `tests/test_report_validator.py`（新建）

**Interfaces:**
- Consumes: `CorrectedReport`、`CorrectionItem`（Task 1）；`bind_structured`（`tradingagents/agents/utils/structured.py`）；`get_instrument_context_from_state`（`tradingagents/agents/utils/agent_utils.py`）；`build_verified_market_snapshot`（`tradingagents/dataflows/market_data_validator.py`）。
- Produces: `create_report_validator(llm, enabled: bool = True) -> Callable[[dict], dict]`。返回的节点读取 state 的 7 个报告字段，返回 `dict`，包含被修正的字段（仅在文本改变时）和始终包含的 `validation_report: str`。`enabled=False` 时返回 `{"validation_report": ""}` 且不做任何 LLM 调用。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_report_validator.py`：

```python
"""Tests for the post-decision report validation node."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import tradingagents.graph.report_validator as rv
from tradingagents.agents.schemas import CorrectedReport, CorrectionItem


def _structured_llm(invoke_return=None, invoke_side_effect=None):
    """Build a fake llm whose with_structured_output(...).invoke(...) is controlled."""
    structured = MagicMock()
    if invoke_side_effect is not None:
        structured.invoke.side_effect = invoke_side_effect
    else:
        structured.invoke.return_value = invoke_return
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm, structured


def _state(**reports):
    base = {
        "company_of_interest": "159241",
        "trade_date": "2026-06-25",
        "instrument_context": "Resolved identity: 航空航天ETF天弘 ...",
    }
    base.update(reports)
    return base


@pytest.mark.unit
def test_corrects_wrong_name(monkeypatch):
    monkeypatch.setattr(rv, "build_verified_market_snapshot", lambda s, d: "SNAPSHOT")
    llm, _ = _structured_llm(
        invoke_return=CorrectedReport(
            corrected_text="航空航天ETF天弘 近期走强。",
            corrections=[CorrectionItem(original="某基金", fixed="航空航天ETF天弘", reason="名称与权威身份不符")],
        )
    )
    node = rv.create_report_validator(llm, enabled=True)
    out = node(_state(market_report="某基金 近期走强。"))

    assert out["market_report"] == "航空航天ETF天弘 近期走强。"
    assert "航空航天ETF天弘" in out["validation_report"]
    assert "某基金" in out["validation_report"]


@pytest.mark.unit
def test_no_change_when_already_correct(monkeypatch):
    monkeypatch.setattr(rv, "build_verified_market_snapshot", lambda s, d: "SNAPSHOT")
    llm, _ = _structured_llm(
        invoke_return=CorrectedReport(corrected_text="原文不变。", corrections=[])
    )
    node = rv.create_report_validator(llm, enabled=True)
    out = node(_state(market_report="原文不变。"))

    assert "market_report" not in out  # unchanged -> not written back
    assert "✅" in out["validation_report"]


@pytest.mark.unit
def test_snapshot_unavailable_skips_number_dimension(monkeypatch):
    def boom(symbol, date):
        raise ValueError("no data")

    monkeypatch.setattr(rv, "build_verified_market_snapshot", boom)
    llm, _ = _structured_llm(
        invoke_return=CorrectedReport(corrected_text="X", corrections=[])
    )
    node = rv.create_report_validator(llm, enabled=True)
    out = node(_state(market_report="X"))

    assert "market_report" not in out
    assert "未校验" in out["validation_report"] or "快照不可用" in out["validation_report"]


@pytest.mark.unit
def test_disabled_passthrough_makes_no_llm_call():
    llm = MagicMock()
    node = rv.create_report_validator(llm, enabled=False)
    out = node(_state(market_report="orig", final_trade_decision="**Rating**: Buy"))

    assert out == {"validation_report": ""}
    llm.with_structured_output.assert_not_called()


@pytest.mark.unit
def test_signal_stable_after_final_decision_correction(monkeypatch):
    from tradingagents.agents.utils.rating import parse_rating

    monkeypatch.setattr(rv, "build_verified_market_snapshot", lambda s, d: "SNAPSHOT")
    original = "**Rating**: Buy\n\n某基金 值得买入。"
    corrected = "**Rating**: Buy\n\n航空航天ETF天弘 值得买入。"
    llm, _ = _structured_llm(
        invoke_return=CorrectedReport(
            corrected_text=corrected,
            corrections=[CorrectionItem(original="某基金", fixed="航空航天ETF天弘", reason="名称不符")],
        )
    )
    node = rv.create_report_validator(llm, enabled=True)
    out = node(_state(final_trade_decision=original))

    assert parse_rating(out["final_trade_decision"]) == parse_rating(original) == "Buy"


@pytest.mark.unit
def test_structured_failure_keeps_original(monkeypatch):
    monkeypatch.setattr(rv, "build_verified_market_snapshot", lambda s, d: "SNAPSHOT")
    llm, _ = _structured_llm(invoke_side_effect=RuntimeError("malformed json"))
    node = rv.create_report_validator(llm, enabled=True)
    out = node(_state(market_report="orig"))

    assert "market_report" not in out
    assert "校验失败" in out["validation_report"]


@pytest.mark.unit
def test_structured_output_unsupported_marks_unverified(monkeypatch):
    monkeypatch.setattr(rv, "build_verified_market_snapshot", lambda s, d: "SNAPSHOT")
    llm = MagicMock()
    llm.with_structured_output.side_effect = NotImplementedError
    node = rv.create_report_validator(llm, enabled=True)
    out = node(_state(market_report="orig"))

    assert "market_report" not in out
    assert "未校验" in out["validation_report"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_report_validator.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'tradingagents.graph.report_validator'`）

- [ ] **Step 3: 写节点实现**

新建 `tradingagents/graph/report_validator.py`：

```python
"""Post-decision report validation node.

The analysts and decision agents are LLMs that can drift on two kinds of
fact: the instrument's *name* and its *exact market numbers*. The
anti-hallucination layer grounds these at the *input* stage (identity injected
into every prompt; ``get_verified_market_snapshot`` for numbers), but nothing
re-checks the generated reports after the fact. This node runs once at the end
of the pipeline (after the Portfolio Manager) and, for each report, asks a
tightly-constrained LLM to correct *only* wrong instrument names and wrong
verifiable numbers — leaving all analysis, opinion, and structure untouched —
then records what it changed in ``validation_report``.

Ground truth is deterministic: the resolved ``instrument_context`` already on
the state, and ``build_verified_market_snapshot`` for the numbers. Either being
unavailable degrades gracefully (that dimension is skipped, never fabricated).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from tradingagents.agents.schemas import CorrectedReport, CorrectionItem
from tradingagents.agents.utils.agent_utils import get_instrument_context_from_state
from tradingagents.agents.utils.structured import bind_structured
from tradingagents.dataflows.market_data_validator import build_verified_market_snapshot

logger = logging.getLogger(__name__)

# (state field, human label) in pipeline order.
REPORT_FIELDS: tuple[tuple[str, str], ...] = (
    ("market_report", "市场分析"),
    ("sentiment_report", "情绪分析"),
    ("news_report", "新闻分析"),
    ("fundamentals_report", "基本面分析"),
    ("investment_plan", "研究经理投资计划"),
    ("trader_investment_plan", "交易员方案"),
    ("final_trade_decision", "最终交易决策"),
)


def _build_ground_truth(state) -> tuple[str, str]:
    """Return (instrument_context, snapshot_or_empty). Never raises."""
    instrument_context = get_instrument_context_from_state(state)
    ticker = str(state["company_of_interest"])
    date = str(state.get("trade_date", ""))
    try:
        snapshot = build_verified_market_snapshot(ticker, date)
    except Exception as exc:  # noqa: BLE001 — unavailability must not crash the run
        logger.info("report_validator: snapshot unavailable for %s (%s)", ticker, exc)
        snapshot = ""
    return instrument_context, snapshot


def _build_prompt(label: str, text: str, instrument_context: str, snapshot: str) -> str:
    snapshot_block = snapshot or "（无可用市场数据快照——数字维度跳过校验，只校验标的名称。）"
    return f"""你是一个严格的报告事实校对器。下面给你一份报告文本，以及该标的的权威信息。

你的唯一任务：找出并修正报告文本中与权威信息不符的【标的名称】和【可验证市场数字】（价格、OHLCV、技术指标值）。

严格规则：
- 只修正错误的标的名称，以及能在下方权威快照里找到对应项的数字。
- 禁止改动任何分析、观点、结论、建议、措辞、语气或结构。不要新增或删除内容，不要翻译，不要重写句子。
- 若某个数字在权威快照里没有对应项，保持原样、不要动。
- 若报告完全正确，corrected_text 必须与原文逐字相同，corrections 为空列表。

【权威标的身份】
{instrument_context}

【权威市场数据快照】
{snapshot_block}

【待校对报告：{label}】
{text}"""


def _correct_field(
    structured_llm,
    label: str,
    text: str,
    instrument_context: str,
    snapshot: str,
) -> tuple[str, list[CorrectionItem], str | None]:
    """Return (corrected_text, corrections, note). note is non-None on skip/failure."""
    if structured_llm is None:
        return text, [], "未校验（结构化输出不可用）"
    prompt = _build_prompt(label, text, instrument_context, snapshot)
    try:
        result: CorrectedReport = structured_llm.invoke(prompt)
        return result.corrected_text, list(result.corrections), None
    except Exception as exc:  # noqa: BLE001 — keep original on any failure, never crash
        logger.warning("report_validator: 校验「%s」失败 (%s)；保留原文", label, exc)
        return text, [], "校验失败（保留原文）"


def _render_validation_report(
    entries: list[tuple[str, list[CorrectionItem], str | None]],
    snapshot: str,
) -> str:
    lines = ["## 报告一致性校验", ""]
    if not snapshot:
        lines += ["- ⚠️ 市场数据快照不可用：数字维度未校验，仅校验标的名称。", ""]

    reported = False
    for label, items, note in entries:
        if note is not None:
            reported = True
            lines += [f"### {label}", f"- ⚠️ {note}", ""]
            continue
        if not items:
            continue
        reported = True
        lines.append(f"### {label}")
        for item in items:
            lines.append(f"- `{item.original}` → `{item.fixed}`（{item.reason}）")
        lines.append("")

    if not reported:
        lines.append("✅ 全部一致，未发现需要修正的标的名称或市场数字。")
    return "\n".join(lines).rstrip() + "\n"


def create_report_validator(llm, enabled: bool = True) -> Callable[[dict], dict]:
    """Build the report-validation node. When disabled, the node is a pass-through."""
    structured_llm = bind_structured(llm, CorrectedReport, "Report Validator") if enabled else None

    def report_validator_node(state) -> dict:
        if not enabled:
            return {"validation_report": ""}

        instrument_context, snapshot = _build_ground_truth(state)
        updates: dict = {}
        entries: list[tuple[str, list[CorrectionItem], str | None]] = []

        for field, label in REPORT_FIELDS:
            text = state.get(field)
            if not isinstance(text, str) or not text.strip():
                continue
            corrected, items, note = _correct_field(
                structured_llm, label, text, instrument_context, snapshot
            )
            if note is None and corrected != text:
                updates[field] = corrected
            entries.append((label, items, note))

        updates["validation_report"] = _render_validation_report(entries, snapshot)
        return updates

    return report_validator_node
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_report_validator.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add tradingagents/graph/report_validator.py tests/test_report_validator.py
git commit -m "feat(graph): add post-decision report validation node"
```

---

### Task 3: 接入图 `setup.py` + `trading_graph.py`

**Files:**
- Modify: `tradingagents/graph/setup.py`（import、`__init__` 增参、`setup_graph` 改末段连边）
- Modify: `tradingagents/graph/trading_graph.py:125-131`（构造 `GraphSetup` 时传开关）
- Test: `tests/test_report_validator_wiring.py`（新建）

**Interfaces:**
- Consumes: `create_report_validator`（Task 2）；`GraphSetup`、`ConditionalLogic`。
- Produces: 编译后的图含名为 `"Report Validator"` 的节点，连边为 `Portfolio Manager → Report Validator → END`；`report_validation_enabled` 配置值经 `GraphSetup` 透传给 `create_report_validator(..., enabled=...)`。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_report_validator_wiring.py`：

```python
"""The report-validation node is wired into the graph after the Portfolio Manager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import tradingagents.graph.setup as setup_mod
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.setup import GraphSetup


@pytest.mark.unit
def test_validator_node_present_and_flag_forwarded(monkeypatch):
    capture: dict = {}

    def fake_factory(llm, enabled=True):
        capture["enabled"] = enabled
        return lambda state: {"validation_report": ""}

    monkeypatch.setattr(setup_mod, "create_report_validator", fake_factory)

    gs = GraphSetup(
        quick_thinking_llm=MagicMock(),
        deep_thinking_llm=MagicMock(),
        tool_nodes={"market": MagicMock()},
        conditional_logic=ConditionalLogic(max_debate_rounds=1, max_risk_discuss_rounds=1),
        analyst_concurrency_limit=1,
        report_validation_enabled=False,
    )
    workflow = gs.setup_graph(("market",))

    assert "Report Validator" in workflow.nodes
    assert capture["enabled"] is False
    # Compiles without error with the extra node + edges.
    workflow.compile()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_report_validator_wiring.py -v`
Expected: FAIL（`TypeError: __init__() got an unexpected keyword argument 'report_validation_enabled'`）

- [ ] **Step 3: 改 `setup.py` — import 与构造参数**

在 `tradingagents/graph/setup.py` 顶部 import 区（第 26 行 `from .conditional_logic import ConditionalLogic` 之后）追加：

```python
from .report_validator import create_report_validator
```

把 `GraphSetup.__init__`（第 32-45 行）改为接收并保存新开关：

```python
    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
        analyst_concurrency_limit: int = 1,
        report_validation_enabled: bool = True,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic
        self.analyst_concurrency_limit = analyst_concurrency_limit
        self.report_validation_enabled = report_validation_enabled
```

- [ ] **Step 4: 改 `setup.py` — 加节点并改末段连边**

在 `setup_graph` 里，`portfolio_manager_node = create_portfolio_manager(self.deep_thinking_llm)`（第 81 行）之后追加创建：

```python
        report_validator_node = create_report_validator(
            self.quick_thinking_llm, enabled=self.report_validation_enabled
        )
```

在 `workflow.add_node("Portfolio Manager", portfolio_manager_node)`（第 100 行）之后追加：

```python
        workflow.add_node("Report Validator", report_validator_node)
```

把末尾的 `workflow.add_edge("Portfolio Manager", END)`（第 170 行）替换为：

```python
        workflow.add_edge("Portfolio Manager", "Report Validator")
        workflow.add_edge("Report Validator", END)
```

- [ ] **Step 5: 改 `trading_graph.py` — 透传配置**

把 `tradingagents/graph/trading_graph.py` 构造 `GraphSetup` 处（第 125-131 行）改为：

```python
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.conditional_logic,
            analyst_concurrency_limit=self.config.get("analyst_concurrency_limit", 1),
            report_validation_enabled=self.config.get("report_validation_enabled", True),
        )
```

- [ ] **Step 6: 运行接线测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_report_validator_wiring.py -v`
Expected: PASS（1 passed）

- [ ] **Step 7: 全量回归 + lint**

Run: `.venv/bin/python -m pytest -m "not integration" -q`
Expected: 全绿（含新建的三组测试），无既有用例回归。

Run: `.venv/bin/ruff check .`
Expected: 无新增告警。

- [ ] **Step 8: 更新 CHANGELOG**

在 `CHANGELOG.md` 的 `## [Unreleased]` 下 `### Added` 追加（无该小节则新建）：

```markdown
- 决策流水线末尾新增报告校验节点：对各报告中的标的名称与可验证市场数字做事实校对、自动修正不一致，并产出 `validation_report` 校验报告。可经 `TRADINGAGENTS_REPORT_VALIDATION_ENABLED` 关闭。
```

- [ ] **Step 9: Commit**

```bash
git add tradingagents/graph/setup.py tradingagents/graph/trading_graph.py tests/test_report_validator_wiring.py CHANGELOG.md
git commit -m "feat(graph): wire report validation node after Portfolio Manager"
```

---

## 备注（设计偏差说明）

- spec 第 6 节原写"结构化输出失败 → 复用 `invoke_structured_or_freetext` 回退（free-text）"。本计划**有意不走 free-text 回退**：free-text 回退只能返回字符串、丢失 `corrections` 结构，且无约束的整篇重写会违反"禁止改动分析"的硬约束。改为：结构化不可用→标"未校验"、结构化调用失败→标"校验失败"并**保留原文**。更安全且仍满足 spec"再失败则保留原文"的最终要求。
- spec 第 7 节"关闭时节点直通透传"通过 `create_report_validator(llm, enabled=False)` 实现：节点始终连入图，但 `enabled=False` 时返回 `{"validation_report": ""}` 且零 LLM 调用——功能等价且便于单测。
- 展示层（CLI/webui 读取 `validation_report`）不在本计划范围，spec 已注明由后续工作决定。

## Self-Review

- **Spec coverage**：范围(名称+数字)→Task 2 `_build_prompt`/ground truth；自动修正→Task 2 写回逻辑；校验报告字段→Task 1 state 字段 + Task 2 `_render_validation_report`；图节点位置→Task 3 连边；错误处理(缺失/失败)→Task 2 `test_snapshot_unavailable`/`test_structured_failure`/`test_structured_output_unsupported`；信号稳定→Task 2 `test_signal_stable...`；配置开关→Task 1 + Task 3 透传 + Task 2 `test_disabled_passthrough`；测试→各 Task TDD。全部有对应任务。
- **Placeholder scan**：无 TBD/TODO；每个改代码的步骤均含完整代码。
- **Type consistency**：`CorrectedReport.corrected_text`/`.corrections`、`CorrectionItem(original/fixed/reason)`、`create_report_validator(llm, enabled)`、`report_validation_enabled` 在 Task 1→2→3 中命名一致；`build_verified_market_snapshot(symbol, curr_date)` 与实现签名一致；`parse_rating` 从 `tradingagents.agents.utils.rating` 导入正确。
