from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


def _is_unavailable_result(result: str) -> bool:
    return result.startswith(
        (
            "NO_DATA_AVAILABLE:",
            "DATA_SOURCE_",
            "DATA_SOURCE_DISABLED:",
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
def get_prediction_markets(
    topic: Annotated[
        str,
        "Event topic/keyword, e.g. 'Fed rate cut', 'recession 2026', "
        "'US election', or a sector/company event.",
    ],
    limit: Annotated[int | None, "Max markets to return; omit for a default of 6"] = None,
) -> str:
    """
    Retrieve live, market-implied probabilities for forward-looking events from
    prediction markets (Polymarket): Fed decisions, recession, elections,
    geopolitics, crypto. Returns the most-traded open markets matching the
    topic, each with its implied probability, traded volume, resolution date,
    and recent move. Uses the configured prediction_markets vendor.

    Args:
        topic (str): Event keyword(s) to search
        limit (int): Max markets to return; omit for a default of 6

    Returns:
        str: A formatted markdown report of matching prediction markets
    """
    prefix_with_evidence, register_dataset_evidence, register_unavailable_evidence = (
        _provenance_helpers()
    )
    result = route_to_vendor("get_prediction_markets", topic, limit)
    query = {"topic": topic, "limit": limit}
    if isinstance(result, str) and _is_unavailable_result(result):
        citation_id = register_unavailable_evidence(
            tool_name="get_prediction_markets",
            vendor="configured vendors",
            query=query,
            reason=result,
        )
        return prefix_with_evidence(result, citation_id, "get_prediction_markets unavailable")
    citation_id = register_dataset_evidence(
        kind="prediction_markets",
        source_name="configured prediction markets vendor",
        title=f"get_prediction_markets: {topic}",
        vendor="configured vendors",
        tool_name="get_prediction_markets",
        query=query,
    )
    return prefix_with_evidence(result, citation_id, f"get_prediction_markets: {topic}")
