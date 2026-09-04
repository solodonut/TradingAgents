"""Live-data tools exposed to the advisor LLM (reused from agent_utils)."""

from tradingagents.agents.utils.agent_utils import (
    get_balance_sheet,
    get_cashflow,
    get_etf_news,
    get_etf_profile,
    get_etf_realtime,
    get_fundamentals,
    get_global_news,
    get_income_statement,
    get_indicators,
    get_insider_transactions,
    get_macro_indicators,
    get_news,
    get_prediction_markets,
    get_stock_data,
)
from tradingagents.dataflows import interface

# Every tool the advisor could call. These are already @tool-decorated LangChain
# tools that internally route through route_to_vendor and never raise (they return
# NO_DATA_AVAILABLE:/DATA_SOURCE_DISABLED: sentinels).
#
# 这是**候选全集**,不要直接绑给 LLM —— 用 get_advisor_tools() 拿当前配置下真正能
# 出数的那部分。
ADVISOR_TOOLS = [
    get_stock_data,
    get_indicators,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_news,
    get_etf_news,
    get_global_news,
    get_insider_transactions,
    get_macro_indicators,
    get_prediction_markets,
    get_etf_profile,
    get_etf_realtime,
]

def _is_routable(method: str) -> bool:
    """当前配置链上是否至少有一家 vendor 实现了这个方法。

    ``disabled`` 链、以及链上全是「配了但没实现该方法」的 vendor(境内模式下的
    ``get_insider_transactions`` 就是后者:链是 eastmoney/tushare/sina,而实现只有
    alpha_vantage 和 yfinance)都会返回 False。
    """
    implementations = interface.VENDOR_METHODS.get(method)
    if implementations is None:
        # 不是路由方法(没有 VENDOR_METHODS 条目)就无从判断,保留 —— 缺证据不等于不可用。
        return True
    chain = interface.get_vendor(interface.get_category_for_method(method), method)
    return any(vendor.strip() in implementations for vendor in chain.split(","))


def get_advisor_tools() -> list:
    """ADVISOR_TOOLS 中当前配置下真能出数的子集。

    按**调用时**的配置判定,不在 import 时冻结 —— config 是进程级单例,
    ``set_config`` 会事后改写它。

    过滤的理由是反幻觉之外的另一件事:把一个必然返回 NO_DATA_AVAILABLE 的工具交给
    模型,只会换来一轮无效 tool call。主图在 ``_create_tool_nodes`` 里用一份写死的
    China-only 白名单做同样的事,这里按可路由性推导,好处是启用新 vendor 后工具会
    自动回来,且不会误删白名单漏掉、但实际可用的方法(如 get_global_news)。
    """
    return [tool for tool in ADVISOR_TOOLS if _is_routable(tool.name)]


_NO_DATA_PREFIXES = (
    "NO_DATA_AVAILABLE:",
    "DATA_SOURCE_DISABLED:",
    "NEED_CONFIRMATION:",
)


def is_no_data(result: str) -> bool:
    """True if a tool return string is an unavailable-data sentinel."""
    return isinstance(result, str) and result.lstrip().startswith(_NO_DATA_PREFIXES)
