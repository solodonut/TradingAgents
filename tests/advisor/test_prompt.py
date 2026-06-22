from tradingagents.advisor.context import build_report_context
from tradingagents.advisor.prompt import build_system_prompt


def test_system_prompt_embeds_report_and_holdings():
    report_ctx = build_report_context(
        {"market_report": "uptrend"}, decision="Buy", ticker="AAPL"
    )
    holdings_ctx = "AAPL: 100 股, 占比 40%"
    prompt = build_system_prompt(report_ctx, holdings_ctx)
    assert "uptrend" in prompt
    assert "40%" in prompt
    assert "引用" in prompt
    assert "免责" in prompt or "投资建议" in prompt
    assert "NO_DATA_AVAILABLE" in prompt


def test_system_prompt_handles_no_holdings():
    prompt = build_system_prompt("report", holdings_ctx="")
    assert "未提供持仓" in prompt


def test_system_prompt_defines_explicit_export_flow_and_success_rules():
    prompt = build_system_prompt("report", holdings_ctx="")

    assert "导出" in prompt
    assert "保存文档" in prompt
    assert "Markdown" in prompt
    assert "总结一下" in prompt
    assert "只在聊天中回答" in prompt
    assert "request_export_scope" in prompt
    assert "2-4" in prompt
    assert "清晰、互斥" in prompt
    assert "完整复述" in prompt
    assert "仍有歧义" in prompt
    assert "绝不猜测" in prompt
    assert "export_chat_report" in prompt
    assert "A/B/C/D" in prompt
    assert "第一个选项" in prompt
    assert "先提供选项" in prompt
    assert "status=saved" in prompt
    assert "原样返回" in prompt
    assert "path" in prompt
