from types import SimpleNamespace
from unittest import mock

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from tradingagents.agents.analysts import news_analyst, sentiment_analyst
from tradingagents.agents.utils.agent_utils import resolve_instrument_identity
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


class CapturingLLM:
    def __init__(self):
        self.bound_tool_names: list[str] = []

    def bind_tools(self, tools):
        self.bound_tool_names = [tool.name for tool in tools]
        return RunnableLambda(lambda _: SimpleNamespace(tool_calls=[], content="ok"))


@pytest.mark.unit
def test_default_config_uses_domestic_china_data_sources_only():
    assert DEFAULT_CONFIG["domestic_china_only"] is True
    assert DEFAULT_CONFIG["data_vendors"]["core_stock_apis"] == "akshare"
    assert DEFAULT_CONFIG["data_vendors"]["technical_indicators"] == "akshare"
    assert DEFAULT_CONFIG["data_vendors"]["fundamental_data"] == "akshare"
    assert DEFAULT_CONFIG["data_vendors"]["news_data"] == "akshare"
    assert DEFAULT_CONFIG["data_vendors"]["macro_data"] == "disabled"
    assert DEFAULT_CONFIG["data_vendors"]["prediction_markets"] == "disabled"


@pytest.mark.unit
def test_news_analyst_hides_overseas_macro_and_prediction_tools_in_china_mode():
    llm = CapturingLLM()
    node = news_analyst.create_news_analyst(llm)

    node(
        {
            "company_of_interest": "159241.SZ",
            "trade_date": "2026-06-17",
            "asset_type": "stock",
            "messages": [HumanMessage(content="analyze")],
        }
    )

    assert llm.bound_tool_names == ["get_news"]


@pytest.mark.unit
def test_sentiment_analyst_skips_stocktwits_and_reddit_in_china_mode():
    llm = mock.Mock()
    llm.with_structured_output.side_effect = AttributeError("unsupported")
    llm.invoke.return_value = SimpleNamespace(content="sentiment")

    with mock.patch.object(sentiment_analyst.get_news, "func", return_value="domestic news"), \
            mock.patch.object(sentiment_analyst, "fetch_stocktwits_messages") as stocktwits, \
            mock.patch.object(sentiment_analyst, "fetch_reddit_posts") as reddit:
        node = sentiment_analyst.create_sentiment_analyst(llm)
        node(
            {
                "company_of_interest": "159241.SZ",
                "trade_date": "2026-06-17",
                "asset_type": "stock",
                "messages": [HumanMessage(content="analyze")],
            }
        )

    stocktwits.assert_not_called()
    reddit.assert_not_called()


@pytest.mark.unit
def test_domestic_china_identity_resolution_skips_yfinance():
    resolve_instrument_identity.cache_clear()
    with mock.patch("tradingagents.agents.utils.agent_utils.yf.Ticker") as ticker:
        assert resolve_instrument_identity("159241.SZ") == {}
    ticker.assert_not_called()


@pytest.mark.unit
def test_domestic_china_return_resolution_skips_yfinance():
    graph = object.__new__(TradingAgentsGraph)
    graph.config = {"domestic_china_only": True}
    with mock.patch("tradingagents.graph.trading_graph.yf.Ticker") as ticker:
        result = graph._fetch_returns("159241.SZ", "2026-06-01", benchmark="399001.SZ")
    assert result == (None, None, None)
    ticker.assert_not_called()
