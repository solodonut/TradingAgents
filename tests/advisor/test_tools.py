from tradingagents.advisor.tools import ADVISOR_TOOLS, is_no_data


def test_advisor_tools_are_langchain_tools():
    names = {t.name for t in ADVISOR_TOOLS}
    assert "get_stock_data" in names
    assert "get_news" in names
    assert "get_fundamentals" in names
    assert "get_indicators" in names


def test_is_no_data_detects_sentinels():
    assert is_no_data("NO_DATA_AVAILABLE: ticker not found")
    assert is_no_data("DATA_SOURCE_DISABLED: reddit off")
    assert is_no_data("NEED_CONFIRMATION: 缺少可用资金池")
    assert not is_no_data("AAPL,2024-01-01,190.0,...")
