"""A股资金面/事件面工具:龙虎榜、融资融券、股东户数、业绩预告(AmazingData 新增维度)。

与 ``fundamental_data_tools`` 同构:每个 ``@tool`` 经 ``route_to_vendor`` 取数并注册
citation evidence(满足报告引用契约)。数据经 AmazingData 常驻服务;服务离线时路由
返回 NO_DATA 兜底句,agent 报告不可用而非编造。
"""

from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


def _provenance_helpers():
    from tradingagents.graph.provenance import (
        prefix_with_evidence,
        register_dataset_evidence,
        register_unavailable_evidence,
    )

    return prefix_with_evidence, register_dataset_evidence, register_unavailable_evidence


def _register_capital_result(tool_name: str, ticker: str, result: str, curr_date: str | None) -> str:
    prefix_with_evidence, register_dataset_evidence, register_unavailable_evidence = (
        _provenance_helpers()
    )
    query = {"ticker": ticker, "curr_date": curr_date}
    if isinstance(result, str) and result.startswith(
        ("NO_DATA_AVAILABLE:", "DATA_SOURCE_UNAVAILABLE:", "DATA_SOURCE_DISABLED:")
    ):
        citation_id = register_unavailable_evidence(
            tool_name=tool_name,
            vendor="AmazingData",
            query=query,
            reason=result,
        )
        return prefix_with_evidence(result, citation_id, f"{tool_name} unavailable")
    citation_id = register_dataset_evidence(
        kind="fundamentals",
        source_name="AmazingData / 银河证券",
        title=f"{tool_name}: {ticker}",
        vendor="AmazingData",
        tool_name=tool_name,
        query=query,
        published_at=curr_date or "",
    )
    return prefix_with_evidence(result, citation_id, f"{tool_name}: {ticker}")


@tool
def get_dragon_tiger(
    ticker: Annotated[str, "A-share ticker symbol"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """获取个股龙虎榜(Dragon-Tiger List)近期上榜明细,包括上榜原因、营业部及买卖金额。
    用于判断游资/机构席位动向与短线资金博弈。仅覆盖沪深 A 股。
    """
    result = route_to_vendor("get_dragon_tiger", ticker, curr_date)
    return _register_capital_result("get_dragon_tiger", ticker, result, curr_date)


@tool
def get_margin_trading(
    ticker: Annotated[str, "A-share ticker symbol"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """获取个股融资融券(Margin Trading)近 20 个交易日明细:融资余额、融资买入/偿还、融券余额。
    融资余额上升多为看多加杠杆,融券余额上升多为看空。仅覆盖沪深 A 股。
    """
    result = route_to_vendor("get_margin_trading", ticker, curr_date)
    return _register_capital_result("get_margin_trading", ticker, result, curr_date)


@tool
def get_shareholders(
    ticker: Annotated[str, "A-share ticker symbol"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """获取股东户数(Shareholder Count)近期各报告期数据。户数下降=筹码集中(多偏多),
    户数上升=筹码分散。仅覆盖沪深 A 股。
    """
    result = route_to_vendor("get_shareholders", ticker, curr_date)
    return _register_capital_result("get_shareholders", ticker, result, curr_date)


@tool
def get_profit_forecast(
    ticker: Annotated[str, "A-share ticker symbol"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """获取业绩预告(Profit Forecast)近期数据:预告净利润区间、同比变动幅度与变动原因。
    是财报正式披露前的重要事件面信号。仅覆盖沪深 A 股。
    """
    result = route_to_vendor("get_profit_forecast", ticker, curr_date)
    return _register_capital_result("get_profit_forecast", ticker, result, curr_date)
