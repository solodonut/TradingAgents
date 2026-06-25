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
                if not items:
                    items = [
                        CorrectionItem(
                            original="(未逐项列出)",
                            fixed="(文本已被校验器修正)",
                            reason="校验器修改了文本但未提供逐项明细",
                        )
                    ]
            entries.append((label, items, note))

        updates["validation_report"] = _render_validation_report(entries, snapshot)
        return updates

    return report_validator_node
