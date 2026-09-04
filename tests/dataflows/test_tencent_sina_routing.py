"""腾讯 / 新浪的路由注册与链序测试。不触网。

两家都是**链尾兜底**档(docs/data-sources.md 9.3.2:新源只放链尾或校验位)。所以最关键的
断言不是「能被调到」,而是「前档成功时**不会**被调到」—— 否则默认行为就被新源改变了,
那不是这次改动的意图。
"""

from __future__ import annotations

from unittest import mock

import pytest

from tradingagents.dataflows import interface

pytestmark = pytest.mark.unit


def test_both_vendors_registered():
    assert "tencent" in interface.VENDOR_LIST
    assert "sina" in interface.VENDOR_LIST


def test_tencent_is_the_only_vendor_for_etf_realtime():
    """IOPV 目前只有腾讯一个源(AKShare 停用后彻底断供)。"""
    assert set(interface.VENDOR_METHODS["get_etf_realtime"]) == {"tencent"}


def test_get_etf_realtime_is_in_a_tools_category():
    """不在任何类别里的方法会让 get_category_for_method 抛 ValueError,路由直接不可用。"""
    assert interface.get_category_for_method("get_etf_realtime") == "etf_data"


@pytest.mark.parametrize(
    ("method", "vendor"),
    [
        ("get_stock_data", "tencent"),
        ("get_news", "sina"),
        ("get_global_news", "sina"),
    ],
)
def test_new_vendors_are_registered_on_their_methods(method, vendor):
    assert vendor in interface.VENDOR_METHODS[method]


@pytest.mark.parametrize(
    ("method", "category", "new_vendor", "args"),
    [
        ("get_stock_data", "core_stock_apis", "tencent", ("600519", "2026-08-01", "2026-09-04")),
        ("get_news", "news_data", "sina", ("600519", "2026-08-01", "2026-09-04")),
    ],
)
def test_new_vendor_not_called_when_earlier_vendor_succeeds(method, category, new_vendor, args):
    """链尾档在前档成功时必须完全不被调用 —— 默认行为不因这次改动而改变。"""
    called = []

    def _spy(*a, **k):
        called.append(new_vendor)
        return f"FROM_{new_vendor.upper()}"

    chain = interface.get_vendor(category, method)
    assert chain.split(",")[-1].strip() == new_vendor, f"{new_vendor} 应在 {method} 链尾: {chain}"
    head = chain.split(",")[0].strip()

    with mock.patch.dict(
        interface.VENDOR_METHODS[method],
        {head: lambda *a, **k: "FROM_HEAD", new_vendor: _spy},
        clear=False,
    ):
        result = interface.route_to_vendor(method, *args)

    assert result == "FROM_HEAD"
    assert called == [], f"{new_vendor} 不该被调用,但被调了"


def test_new_vendor_serves_the_call_when_every_earlier_vendor_fails():
    """前档全挂时链尾档必须真的接得住 —— 否则加这一档没有意义。

    刻意**不**在这里设 config:走默认链,这样默认配置里漏了 sina 就会失败。
    """
    from tradingagents.dataflows.errors import NoMarketDataError

    chain = [v.strip() for v in interface.get_vendor("news_data", "get_news").split(",")]
    assert chain[-1] == "sina", f"sina 应在 get_news 默认链尾: {chain}"

    def _dead(*a, **k):
        raise NoMarketDataError("600519", "600519", "vendor down")

    patched = dict.fromkeys(chain[:-1], _dead)
    patched["sina"] = lambda *a, **k: "FROM_SINA"

    with mock.patch.dict(interface.VENDOR_METHODS["get_news"], patched, clear=False):
        result = interface.route_to_vendor("get_news", "600519", "2026-08-01", "2026-09-04")

    assert result == "FROM_SINA"


def test_etf_realtime_routes_to_tencent():
    with mock.patch.dict(
        interface.VENDOR_METHODS["get_etf_realtime"],
        {"tencent": lambda *a, **k: "FROM_TENCENT"},
        clear=False,
    ):
        assert interface.route_to_vendor("get_etf_realtime", "510300", "2026-09-04") == "FROM_TENCENT"


def test_etf_profile_chain_unchanged():
    """腾讯刻意**不**进 get_etf_profile:它没有份额/成分,放链首会挤掉 Tushare 的完整画像。"""
    assert "tencent" not in interface.VENDOR_METHODS["get_etf_profile"]


def test_etf_realtime_tool_is_exposed_to_agents():
    """方法登记了但没暴露成 @tool,agent 就永远拿不到 IOPV。"""
    from tradingagents.agents.utils import agent_utils

    assert "get_etf_realtime" in agent_utils.__all__
    assert hasattr(agent_utils, "get_etf_realtime")
