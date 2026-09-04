from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_etf_profile(
    symbol: Annotated[str, "mainland China listed ETF/fund code, e.g. 510300 or 510300.SS"],
    curr_date: Annotated[str, "current date, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve the structural profile of a mainland China listed fund/ETF: fund
    scale, tracked index, and top-10 constituent holdings.

    Use this for ETF symbols instead of company-fundamentals tools — ETFs track
    a basket/index, so analyze scale/liquidity and holdings concentration rather
    than financial statements. For live discount/premium vs IOPV, use
    get_etf_realtime instead — this tool does not provide it. Returns
    NO_DATA_AVAILABLE for non-ETF symbols (individual stocks, overseas tickers).
    Args:
        symbol (str): ETF/fund code, e.g. 510300 or 510300.SS
        curr_date (str): Current date, yyyy-mm-dd (selects the holdings year)
    Returns:
        str: A formatted report with fund scale, tracked index and holdings
    """
    return route_to_vendor("get_etf_profile", symbol, curr_date)


@tool
def get_etf_realtime(
    symbol: Annotated[str, "mainland China listed ETF/fund code, e.g. 510300 or 510300.SS"],
    curr_date: Annotated[str, "current date, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve the live realtime snapshot of a mainland China listed fund/ETF:
    last price, IOPV (indicative optimized portfolio value), the discount/premium
    of price vs IOPV, and the T-1 unit NAV.

    This is the only tool that provides IOPV and discount/premium. Use it when
    assessing whether an ETF is trading rich or cheap against its underlying
    basket — a persistent premium signals crowded demand or arbitrage friction, a
    discount the reverse. Pair it with get_etf_profile for scale and holdings.
    Values are intraday-live and NOT usable for historical/backtest dates.
    Returns NO_DATA_AVAILABLE for non-fund symbols and overseas tickers.
    Args:
        symbol (str): ETF/fund code, e.g. 510300 or 510300.SS
        curr_date (str): Current date, yyyy-mm-dd
    Returns:
        str: A formatted report with last price, IOPV, premium/discount and NAV
    """
    return route_to_vendor("get_etf_realtime", symbol, curr_date)
