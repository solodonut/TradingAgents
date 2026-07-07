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


def _register_fundamental_result(
    tool_name: str,
    ticker: str,
    result: str,
    *,
    freq: str | None = None,
    curr_date: str | None = None,
) -> str:
    prefix_with_evidence, register_dataset_evidence, register_unavailable_evidence = (
        _provenance_helpers()
    )
    query = {"ticker": ticker, "freq": freq, "curr_date": curr_date}
    if isinstance(result, str) and result.startswith(
        ("NO_DATA_AVAILABLE:", "DATA_SOURCE_UNAVAILABLE:", "DATA_SOURCE_DISABLED:")
    ):
        citation_id = register_unavailable_evidence(
            tool_name=tool_name,
            vendor="configured vendors",
            query=query,
            reason=result,
        )
        return prefix_with_evidence(result, citation_id, f"{tool_name} unavailable")
    citation_id = register_dataset_evidence(
        kind="fundamentals",
        source_name="configured fundamentals vendor",
        title=f"{tool_name}: {ticker}",
        vendor="configured vendors",
        tool_name=tool_name,
        query=query,
        published_at=curr_date or "",
    )
    return prefix_with_evidence(result, citation_id, f"{tool_name}: {ticker}")


@tool
def get_fundamentals(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"],
) -> str:
    """
    Retrieve comprehensive fundamental data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing comprehensive fundamental data
    """
    result = route_to_vendor("get_fundamentals", ticker, curr_date)
    return _register_fundamental_result(
        "get_fundamentals",
        ticker,
        result,
        curr_date=curr_date,
    )


@tool
def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve balance sheet data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing balance sheet data
    """
    result = route_to_vendor("get_balance_sheet", ticker, freq, curr_date)
    return _register_fundamental_result(
        "get_balance_sheet",
        ticker,
        result,
        freq=freq,
        curr_date=curr_date,
    )


@tool
def get_cashflow(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve cash flow statement data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing cash flow statement data
    """
    result = route_to_vendor("get_cashflow", ticker, freq, curr_date)
    return _register_fundamental_result(
        "get_cashflow",
        ticker,
        result,
        freq=freq,
        curr_date=curr_date,
    )


@tool
def get_income_statement(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "reporting frequency: annual/quarterly"] = "quarterly",
    curr_date: Annotated[str, "current date you are trading at, yyyy-mm-dd"] = None,
) -> str:
    """
    Retrieve income statement data for a given ticker symbol.
    Uses the configured fundamental_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
        freq (str): Reporting frequency: annual/quarterly (default quarterly)
        curr_date (str): Current date you are trading at, yyyy-mm-dd
    Returns:
        str: A formatted report containing income statement data
    """
    result = route_to_vendor("get_income_statement", ticker, freq, curr_date)
    return _register_fundamental_result(
        "get_income_statement",
        ticker,
        result,
        freq=freq,
        curr_date=curr_date,
    )
