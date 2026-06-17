from tradingagents.advisor.context import build_report_context


def test_build_report_context_includes_present_fields():
    result = {
        "market_report": "RSI 65, uptrend",
        "final_trade_decision": "**Rating**: Buy",
    }
    ctx = build_report_context(result, decision="Buy", ticker="AAPL")
    assert "AAPL" in ctx
    assert "Buy" in ctx
    assert "RSI 65" in ctx
    assert "市场分析" in ctx
    assert "新闻分析" not in ctx


def test_build_report_context_empty_result():
    ctx = build_report_context(None, decision=None, ticker="AAPL")
    assert "AAPL" in ctx
    assert "无可用报告" in ctx
