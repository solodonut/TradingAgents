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


@tool
def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve stock price data (OHLCV) for a given ticker symbol.
    Uses the configured core_stock_apis vendor.
    Args:
        symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted dataframe containing the stock price data for the specified ticker symbol in the specified date range.
    """
    prefix_with_evidence, register_dataset_evidence, register_unavailable_evidence = (
        _provenance_helpers()
    )
    result = route_to_vendor("get_stock_data", symbol, start_date, end_date)
    query = {"ticker": symbol, "start_date": start_date, "end_date": end_date}
    if isinstance(result, str) and result.startswith(
        ("NO_DATA_AVAILABLE:", "DATA_SOURCE_", "DATA_SOURCE_DISABLED:")
    ):
        citation_id = register_unavailable_evidence(
            tool_name="get_stock_data",
            vendor="configured vendors",
            query=query,
            reason=result,
        )
        return prefix_with_evidence(result, citation_id, "get_stock_data unavailable")
    citation_id = register_dataset_evidence(
        kind="market_data",
        source_name="configured market data vendor",
        title=f"get_stock_data: {symbol}",
        vendor="configured vendors",
        tool_name="get_stock_data",
        query=query,
        published_at=f"{start_date}..{end_date}",
    )
    return prefix_with_evidence(result, citation_id, f"get_stock_data: {symbol}")
