from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_etf_profile(
    symbol: Annotated[str, "mainland China listed ETF/fund code, e.g. 510300 or 510300.SS"],
    curr_date: Annotated[str, "current date, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve ETF-specific data for a mainland China listed fund/ETF: discount/
    premium vs IOPV, fund scale, and top-10 constituent holdings.

    Use this for ETF symbols instead of company-fundamentals tools — ETFs track
    a basket/index, so analyze premium/discount, scale/liquidity and holdings
    concentration rather than financial statements. Returns NO_DATA_AVAILABLE for
    non-ETF symbols (individual stocks, overseas tickers).
    Args:
        symbol (str): ETF/fund code, e.g. 510300 or 510300.SS
        curr_date (str): Current date, yyyy-mm-dd (selects the holdings year)
    Returns:
        str: A formatted report with discount/premium, IOPV, scale and holdings
    """
    return route_to_vendor("get_etf_profile", symbol, curr_date)
