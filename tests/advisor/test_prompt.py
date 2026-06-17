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
