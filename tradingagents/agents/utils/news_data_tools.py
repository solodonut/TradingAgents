from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


def _is_unavailable_result(result: str) -> bool:
    return result.startswith(
        (
            "NO_DATA_AVAILABLE:",
            "DATA_SOURCE_",
            "DATA_SOURCE_DISABLED:",
            "Error fetching news",
        )
    )


def _provenance_helpers():
    from tradingagents.graph.provenance import (
        prefix_with_evidence,
        register_dataset_evidence,
        register_unavailable_evidence,
    )

    return prefix_with_evidence, register_dataset_evidence, register_unavailable_evidence


@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    prefix_with_evidence, register_dataset_evidence, register_unavailable_evidence = (
        _provenance_helpers()
    )
    result = route_to_vendor("get_news", ticker, start_date, end_date)
    query = {"ticker": ticker, "start_date": start_date, "end_date": end_date}
    if isinstance(result, str) and _is_unavailable_result(result):
        citation_id = register_unavailable_evidence(
            tool_name="get_news",
            vendor="configured vendors",
            query=query,
            reason=result,
        )
        return prefix_with_evidence(result, citation_id, "get_news unavailable")
    citation_id = register_dataset_evidence(
        kind="news",
        source_name="configured news vendor",
        title=f"get_news: {ticker}",
        vendor="configured vendors",
        tool_name="get_news",
        query=query,
        published_at=f"{start_date}..{end_date}",
    )
    return prefix_with_evidence(result, citation_id, f"get_news: {ticker}")

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int | None, "Days to look back; omit to use the configured default"] = None,
    limit: Annotated[int | None, "Max articles to return; omit to use the configured default"] = None,
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor. Defaults for look_back_days and
    limit come from DEFAULT_CONFIG (global_news_lookback_days,
    global_news_article_limit); pass explicit values to override.

    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back; omit to inherit config
        limit (int): Maximum number of articles to return; omit to inherit config

    Returns:
        str: A formatted string containing global news data
    """
    prefix_with_evidence, register_dataset_evidence, register_unavailable_evidence = (
        _provenance_helpers()
    )
    result = route_to_vendor("get_global_news", curr_date, look_back_days, limit)
    query = {"curr_date": curr_date, "look_back_days": look_back_days, "limit": limit}
    if isinstance(result, str) and _is_unavailable_result(result):
        citation_id = register_unavailable_evidence(
            tool_name="get_global_news",
            vendor="configured vendors",
            query=query,
            reason=result,
        )
        return prefix_with_evidence(result, citation_id, "get_global_news unavailable")
    citation_id = register_dataset_evidence(
        kind="news",
        source_name="configured news vendor",
        title="get_global_news",
        vendor="configured vendors",
        tool_name="get_global_news",
        query=query,
        published_at=curr_date,
    )
    return prefix_with_evidence(result, citation_id, "get_global_news")

@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """
    Retrieve insider transaction information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
    Returns:
        str: A report of insider transaction data
    """
    prefix_with_evidence, register_dataset_evidence, register_unavailable_evidence = (
        _provenance_helpers()
    )
    result = route_to_vendor("get_insider_transactions", ticker)
    query = {"ticker": ticker}
    if isinstance(result, str) and _is_unavailable_result(result):
        citation_id = register_unavailable_evidence(
            tool_name="get_insider_transactions",
            vendor="configured vendors",
            query=query,
            reason=result,
        )
        return prefix_with_evidence(
            result, citation_id, "get_insider_transactions unavailable"
        )
    citation_id = register_dataset_evidence(
        kind="news",
        source_name="configured news vendor",
        title=f"get_insider_transactions: {ticker}",
        vendor="configured vendors",
        tool_name="get_insider_transactions",
        query=query,
        published_at="",
    )
    return prefix_with_evidence(
        result, citation_id, f"get_insider_transactions: {ticker}"
    )
