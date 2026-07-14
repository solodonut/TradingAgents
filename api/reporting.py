"""Markdown report rendering helpers shared by WebUI download routes."""

from __future__ import annotations

import re

from tradingagents.graph.evidence import extract_cited_evidence_ids, render_source_table

_REPORT_ORDER = [
    ("market_report", "市场分析"),
    ("sentiment_report", "情绪分析"),
    ("news_report", "新闻分析"),
    ("fundamentals_report", "基本面分析"),
    ("investment_plan", "研究经理决策"),
    ("trader_investment_plan", "交易计划"),
    ("final_trade_decision", "组合经理最终决策"),
    ("validation_report", "报告一致性校验"),
]


def build_markdown_report(run) -> str:
    title = f"{run.ticker} {run.instrument_name}" if run.instrument_name else run.ticker
    parts = [f"# TradingAgents 分析报告 — {title} ({run.trade_date})\n"]
    if run.decision:
        parts.append(f"**决策: {run.decision}**\n")
    result = run.result or {}
    evidence_items = result.get("evidence_items") or []
    all_cited: list[str] = []
    seen_global: set[str] = set()
    for key, section_title in _REPORT_ORDER:
        content = result.get(key)
        if content:
            parts.append(f"\n## {section_title}\n\n{content}\n")
            citation_ids = extract_cited_evidence_ids(content, evidence_items)
            for citation_id in citation_ids:
                if citation_id not in seen_global:
                    seen_global.add(citation_id)
                    all_cited.append(citation_id)
            table = render_source_table(evidence_items, citation_ids, heading="引用来源")
            if table:
                parts.append(f"\n{table}\n")
    global_table = render_source_table(evidence_items, all_cited, heading="全部数据来源")
    if global_table:
        parts.append("\n" + _promote_first_heading(global_table) + "\n")
    return "\n".join(parts)


def report_filename(run) -> str:
    name = f"{run.ticker}_{run.instrument_name}" if run.instrument_name else run.ticker
    return f"{_safe_filename_part(name)}_{_safe_filename_part(run.trade_date)}.md"


def _safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\s]+", "_", value.strip())
    return cleaned.strip("._") or "report"


def _promote_first_heading(markdown: str) -> str:
    return markdown.replace("### ", "## ", 1)
