from tradingagents.advisor.tools import ADVISOR_TOOLS, get_advisor_tools, is_no_data
from tradingagents.dataflows.config import set_config


def test_advisor_tools_are_langchain_tools():
    names = {t.name for t in ADVISOR_TOOLS}
    assert "get_stock_data" in names
    assert "get_news" in names
    assert "get_fundamentals" in names
    assert "get_indicators" in names
    assert "get_etf_profile" in names


def test_unroutable_tools_are_not_handed_to_the_llm():
    """配置链里没有任何一家实现该方法时,工具不该出现在 LLM 的工具集里。

    默认(境内)配置下这三个方法一档都不可用:internal transactions 只有
    alpha_vantage/yfinance 两个海外实现,宏观与预测市场整条链是 disabled。
    暴露出去只会让模型白调一轮再拿回哨兵字符串。
    """
    names = {t.name for t in get_advisor_tools()}

    assert "get_insider_transactions" not in names
    assert "get_macro_indicators" not in names
    assert "get_prediction_markets" not in names


def test_routable_tools_are_still_handed_to_the_llm():
    """过滤不能过头 —— 链上有实现的方法必须保留。

    尤其是 get_global_news:主图的 China-only 白名单把它排除了,但它实际由
    tushare+sina 供数,照抄那份白名单会白丢一个能用的能力。
    """
    names = {t.name for t in get_advisor_tools()}

    assert "get_global_news" in names
    assert "get_stock_data" in names
    assert "get_etf_realtime" in names


def test_tool_reappears_when_an_implementing_vendor_is_configured():
    """可用性按调用时的配置判定,不是 import 时冻结。

    config 是进程级单例、会被 set_config 事后改写;如果过滤发生在模块导入时,
    这里改完配置工具也不会回来。
    """
    set_config({"tool_vendors": {"get_insider_transactions": "alpha_vantage"}})

    names = {t.name for t in get_advisor_tools()}

    assert "get_insider_transactions" in names


def test_is_no_data_detects_sentinels():
    assert is_no_data("NO_DATA_AVAILABLE: ticker not found")
    assert is_no_data("DATA_SOURCE_DISABLED: reddit off")
    assert is_no_data("NEED_CONFIRMATION: 缺少可用资金池")
    assert not is_no_data("AAPL,2024-01-01,190.0,...")
