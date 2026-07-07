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
def get_macro_indicators(
    indicator: Annotated[
        str,
        "Macro indicator: a friendly alias such as 'cpi', 'core_pce', "
        "'unemployment', 'fed_funds_rate', '10y_treasury', 'yield_curve', "
        "'real_gdp', 'vix', or a raw FRED series ID such as 'CPIAUCSL'.",
    ],
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format; the end of the window"],
    look_back_days: Annotated[
        int | None, "Trailing window length in days; omit for a 1-year window"
    ] = None,
) -> str:
    """
    Retrieve a macroeconomic indicator time series from FRED (Federal Reserve
    Economic Data): policy rates, Treasury yields, inflation, labor, and growth.
    Returns the series title, units, frequency, the latest value, the change
    over the window, and a recent observation table. Uses the configured
    macro_data vendor.

    Args:
        indicator (str): Friendly alias or raw FRED series ID
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Trailing window length; omit for a 1-year window

    Returns:
        str: A formatted markdown report of the macro series
    """
    prefix_with_evidence, register_dataset_evidence, register_unavailable_evidence = (
        _provenance_helpers()
    )
    result = route_to_vendor("get_macro_indicators", indicator, curr_date, look_back_days)
    query = {"indicator": indicator, "curr_date": curr_date, "look_back_days": look_back_days}
    if isinstance(result, str) and _is_unavailable_result(result):
        citation_id = register_unavailable_evidence(
            tool_name="get_macro_indicators",
            vendor="configured vendors",
            query=query,
            reason=result,
        )
        return prefix_with_evidence(result, citation_id, "get_macro_indicators unavailable")
    citation_id = register_dataset_evidence(
        kind="macro_data",
        source_name="configured macro vendor",
        title=f"get_macro_indicators: {indicator}",
        vendor="configured vendors",
        tool_name="get_macro_indicators",
        query=query,
        published_at=curr_date,
    )
    return prefix_with_evidence(result, citation_id, f"get_macro_indicators: {indicator}")
