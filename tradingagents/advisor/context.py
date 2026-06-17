"""Assemble a completed analysis run's reports into LLM context text."""

# (field_key, human title) — mirrors api/routes/analysis.py:_REPORT_ORDER
_REPORT_ORDER = [
    ("market_report", "市场分析"),
    ("sentiment_report", "情绪分析"),
    ("news_report", "新闻分析"),
    ("fundamentals_report", "基本面分析"),
    ("investment_plan", "研究经理决策"),
    ("trader_investment_plan", "交易计划"),
    ("final_trade_decision", "组合经理最终决策"),
]


def build_report_context(
    result: dict | None, decision: str | None, ticker: str
) -> str:
    """Render the 7 report fields present in `result` into a markdown block."""
    parts = [f"# 标的 {ticker} 的 TradingAgents 分析报告"]
    if decision:
        parts.append(f"**最终评级: {decision}**")
    rendered_any = False
    if result:
        for key, title in _REPORT_ORDER:
            content = result.get(key)
            if content:
                rendered_any = True
                parts.append(f"\n## {title}\n\n{content}")
    if not rendered_any:
        parts.append("\n(无可用报告 — 用户尚未关联已完成的分析,或报告为空)")
    return "\n".join(parts)
