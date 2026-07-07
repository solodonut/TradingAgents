from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


def _is_unavailable_result(result: str) -> bool:
    return result.startswith(
        ("NO_DATA_AVAILABLE:", "DATA_SOURCE_UNAVAILABLE:", "DATA_SOURCE_DISABLED:")
    )


def _provenance_helpers():
    from tradingagents.graph.provenance import (
        prefix_with_evidence,
        register_dataset_evidence,
        register_unavailable_evidence,
    )

    return prefix_with_evidence, register_dataset_evidence, register_unavailable_evidence


@tool
def get_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"] = 30,
) -> str:
    """
    Retrieve a single technical indicator for a given ticker symbol.
    Uses the configured technical_indicators vendor.
    Args:
        symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
        indicator (str): A single technical indicator name, e.g. 'rsi', 'macd'. Call this tool once per indicator.
        curr_date (str): The current trading date you are trading on, YYYY-mm-dd
        look_back_days (int): How many days to look back, default is 30
    Returns:
        str: A formatted dataframe containing the technical indicators for the specified ticker symbol and indicator.
    """
    # LLMs sometimes pass multiple indicators as a comma-separated string;
    # split and process each individually.
    prefix_with_evidence, register_dataset_evidence, register_unavailable_evidence = (
        _provenance_helpers()
    )
    indicators = [i.strip().lower() for i in indicator.split(",") if i.strip()]
    results = []
    for ind in indicators:
        try:
            result = route_to_vendor("get_indicators", symbol, ind, curr_date, look_back_days)
        except ValueError as e:
            results.append(str(e))
            continue
        query = {
            "ticker": symbol,
            "indicator": ind,
            "curr_date": curr_date,
            "look_back_days": look_back_days,
        }
        if isinstance(result, str) and _is_unavailable_result(result):
            citation_id = register_unavailable_evidence(
                tool_name="get_indicators",
                vendor="configured vendors",
                query=query,
                reason=result,
            )
            results.append(
                prefix_with_evidence(result, citation_id, "get_indicators unavailable")
            )
            continue
        citation_id = register_dataset_evidence(
            kind="market_data",
            source_name="configured technical indicator vendor",
            title=f"get_indicators: {symbol} {ind}",
            vendor="configured vendors",
            tool_name="get_indicators",
            query=query,
            published_at=f"{look_back_days} days ending {curr_date}",
        )
        results.append(
            prefix_with_evidence(result, citation_id, f"get_indicators: {symbol} {ind}")
        )
    return "\n\n".join(results)
