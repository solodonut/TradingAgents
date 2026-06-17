"""The market analyst is bound (and prompt-instructed) to call
get_verified_market_snapshot; if the executor ToolNode doesn't register it, the
call fails and the model reports the tool "unavailable" and skips verification.

Regression guard for that wiring gap (snapshot bound to the LLM but missing from
the market ToolNode).
"""
import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph


@pytest.mark.unit
def test_market_toolnode_can_execute_verified_snapshot():
    # _create_tool_nodes does not use self -> call unbound (avoids building LLMs).
    nodes = TradingAgentsGraph._create_tool_nodes(None)
    market_tools = set(nodes["market"].tools_by_name)
    assert "get_verified_market_snapshot" in market_tools, (
        "get_verified_market_snapshot is bound to the market analyst but not "
        "registered in the market ToolNode, so the model's call fails."
    )
    # the other core market tools must remain too
    assert {"get_stock_data", "get_indicators"} <= market_tools


@pytest.mark.unit
def test_news_toolnode_degrades_vendor_error_instead_of_crashing():
    # Regression for the 159241.SZ run: get_macro_indicators raised
    # FredNotConfiguredError (a VendorError) with no FRED_API_KEY, and the
    # ToolNode re-raised it, crashing the whole graph before any final decision.
    # Every data ToolNode must register a handler that turns a VendorError into
    # an error ToolMessage so the analyst reports the source unavailable instead.
    from tradingagents.dataflows.errors import VendorError
    from tradingagents.graph.trading_graph import _handle_vendor_tool_error

    nodes = TradingAgentsGraph._create_tool_nodes(None)
    for name in ("market", "social", "news", "fundamentals"):
        assert nodes[name]._handle_tool_errors is _handle_vendor_tool_error, (
            f"{name} ToolNode must handle VendorError, else a missing data "
            f"source crashes the whole graph."
        )

    out = _handle_vendor_tool_error(VendorError("FRED_API_KEY is not set."))
    assert "FRED_API_KEY" in out
    assert "fabricate" in out
