from types import SimpleNamespace
from unittest import mock

import pandas as pd
import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from tradingagents.agents.analysts import news_analyst, sentiment_analyst
from tradingagents.agents.utils.agent_utils import resolve_instrument_identity
from tradingagents.dataflows.akshare_fundamentals import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
)
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
    assert DEFAULT_CONFIG["data_vendors"]["core_stock_apis"] == "tushare,akshare"
    assert DEFAULT_CONFIG["data_vendors"]["technical_indicators"] == "tushare,akshare"
    assert DEFAULT_CONFIG["data_vendors"]["fundamental_data"] == "tushare,akshare"
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
    # A-shares resolve their name from the domestic source (not overseas
    # yfinance) so the analyst prompt carries the real instrument name.
    resolve_instrument_identity.cache_clear()
    with mock.patch(
        "tradingagents.dataflows.ticker_name.resolve_ticker_name",
        return_value="航空航天ETF天弘",
    ), mock.patch("tradingagents.agents.utils.agent_utils.yf.Ticker") as ticker:
        assert resolve_instrument_identity("159241.SZ") == {
            "company_name": "航空航天ETF天弘"
        }
    ticker.assert_not_called()


@pytest.mark.unit
def test_domestic_china_return_resolution_skips_yfinance():
    graph = object.__new__(TradingAgentsGraph)
    graph.config = {"domestic_china_only": True}
    with mock.patch("tradingagents.graph.trading_graph.yf.Ticker") as ticker:
        result = graph._fetch_returns("159241.SZ", "2026-06-01", benchmark="399001.SZ")
    assert result == (None, None, None)
    ticker.assert_not_called()


@pytest.mark.unit
def test_akshare_etf_fundamentals_use_domestic_fund_data():
    spot = pd.DataFrame(
        [
            {
                "代码": "159241",
                "名称": "国防ETF",
                "最新价": 1.234,
                "涨跌幅": 2.5,
                "成交额": 12345678,
            }
        ]
    )
    nav = pd.DataFrame(
        [
            {"净值日期": "2026-06-18", "单位净值": 1.22, "累计净值": 1.22},
            {"净值日期": "2026-06-19", "单位净值": 1.23, "累计净值": 1.23},
        ]
    )

    def uncached(_key, _ttl, func):
        return func()

    with mock.patch(
        "tradingagents.dataflows.akshare_fundamentals.cached_call",
        side_effect=uncached,
    ), mock.patch(
        "tradingagents.dataflows.akshare_fundamentals.ak_retry",
        side_effect=lambda func: func(),
    ), mock.patch(
        "tradingagents.dataflows.akshare_fundamentals.ak.fund_etf_spot_em",
        return_value=spot,
    ), mock.patch(
        "tradingagents.dataflows.akshare_fundamentals.ak.fund_etf_fund_info_em",
        return_value=nav,
    ), mock.patch(
        "tradingagents.dataflows.akshare_fundamentals.ak.stock_financial_analysis_indicator"
    ) as stock_ratios:
        result = get_fundamentals("159241", "2026-06-19")

    assert "Fund/ETF Fundamentals for 159241.SZ" in result
    assert "国防ETF" in result
    assert "ETF Spot Snapshot" in result
    assert "Recent NAV History" in result
    stock_ratios.assert_not_called()


@pytest.mark.unit
def test_akshare_etf_company_statements_are_not_applicable():
    for result in (
        get_balance_sheet("159241", curr_date="2026-06-19"),
        get_income_statement("159241", curr_date="2026-06-19"),
        get_cashflow("159241", curr_date="2026-06-19"),
    ):
        assert "ETF/Fund" in result
        assert "not_applicable" in result
        assert "do not publish operating-company financial statements" in result
