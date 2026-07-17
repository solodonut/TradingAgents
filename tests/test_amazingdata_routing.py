"""AmazingData vendor 路由测试:链首优先 + 探测降级回退。不触网。

用 ``mock.patch.dict`` 替换 ``VENDOR_METHODS`` 里的实现,验证路由行为(链首=amazingdata、
服务离线抛 NotConfigured 时回退 tushare/akshare、capital_flow_data 新类别可解析)。
"""

from unittest import mock

import pytest

from tradingagents.dataflows import config, interface
from tradingagents.dataflows.amazingdata_utils import (
    AmazingdataNotConfiguredError,
    AmazingdataRateLimitError,
)

pytestmark = pytest.mark.unit


def test_amazingdata_is_chain_head_for_core_apis():
    config.set_config({"data_vendors": {"core_stock_apis": "amazingdata,tushare,akshare"}})
    with mock.patch.dict(
        interface.VENDOR_METHODS["get_stock_data"],
        {
            "amazingdata": lambda *a, **k: "FROM_AMAZINGDATA",
            "tushare": lambda *a, **k: "FROM_TUSHARE",
        },
        clear=False,
    ):
        result = interface.route_to_vendor("get_stock_data", "600519.SH", "2026-06-01", "2026-07-10")
    assert result == "FROM_AMAZINGDATA"


def test_falls_back_to_tushare_when_amazingdata_offline():
    config.set_config({"data_vendors": {"core_stock_apis": "amazingdata,tushare"}})

    def _offline(*a, **k):
        raise AmazingdataNotConfiguredError("service offline")

    with mock.patch.dict(
        interface.VENDOR_METHODS["get_stock_data"],
        {"amazingdata": _offline, "tushare": lambda *a, **k: "FROM_TUSHARE"},
        clear=False,
    ):
        result = interface.route_to_vendor("get_stock_data", "600519.SH", "2026-06-01", "2026-07-10")
    assert result == "FROM_TUSHARE"


def test_falls_back_on_rate_limit_connect_failed():
    config.set_config({"data_vendors": {"fundamental_data": "amazingdata,tushare"}})

    def _connect_failed(*a, **k):
        raise AmazingdataRateLimitError("HTTP 403: Connect failed")

    with mock.patch.dict(
        interface.VENDOR_METHODS["get_balance_sheet"],
        {"amazingdata": _connect_failed, "tushare": lambda *a, **k: "FROM_TUSHARE"},
        clear=False,
    ):
        result = interface.route_to_vendor("get_balance_sheet", "600519.SH", "quarterly", "2026-07-10")
    assert result == "FROM_TUSHARE"


def test_capital_flow_category_resolves_and_routes():
    # capital_flow_data 是新类别;未配置时用 "default" -> 全部可用 vendor(仅 amazingdata)。
    config.set_config({})
    assert interface.get_category_for_method("get_dragon_tiger") == "capital_flow_data"
    with mock.patch.dict(
        interface.VENDOR_METHODS["get_dragon_tiger"],
        {"amazingdata": lambda *a, **k: "LHB_DATA"},
        clear=False,
    ):
        result = interface.route_to_vendor("get_dragon_tiger", "002594.SZ", "2026-07-10")
    assert result == "LHB_DATA"


def test_capital_flow_offline_returns_no_data_sentinel():
    # 仅 amazingdata 覆盖;离线时无回退 -> NO_DATA 兜底句(不 crash),因抛 NoMarketData。
    config.set_config({})
    from tradingagents.dataflows.errors import NoMarketDataError

    def _no_data(*a, **k):
        raise NoMarketDataError("002594.SZ", "002594.SZ", "no records")

    with mock.patch.dict(
        interface.VENDOR_METHODS["get_dragon_tiger"],
        {"amazingdata": _no_data},
        clear=True,
    ):
        result = interface.route_to_vendor("get_dragon_tiger", "002594.SZ", "2026-07-10")
    assert result.startswith("NO_DATA_AVAILABLE:")
