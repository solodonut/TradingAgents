"""Live-data tools exposed to the advisor LLM (reused from agent_utils)."""

from tradingagents.agents.utils.agent_utils import (
    get_balance_sheet,
    get_cashflow,
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

# Tools the advisor may call during a conversation. These are already
# @tool-decorated LangChain tools that internally route through route_to_vendor
# and never raise (they return NO_DATA_AVAILABLE:/DATA_SOURCE_DISABLED: sentinels).
ADVISOR_TOOLS = [
    get_stock_data,
    get_indicators,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_news,
    get_global_news,
    get_insider_transactions,
    get_macro_indicators,
    get_prediction_markets,
]

_NO_DATA_PREFIXES = (
    "NO_DATA_AVAILABLE:",
    "DATA_SOURCE_DISABLED:",
    "NEED_CONFIRMATION:",
)


def is_no_data(result: str) -> bool:
    """True if a tool return string is an unavailable-data sentinel."""
    return isinstance(result, str) and result.lstrip().startswith(_NO_DATA_PREFIXES)
