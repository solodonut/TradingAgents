from tradingagents.dataflows.diagnostics import classify_result
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)


def test_classify_ok_plain_string():
    assert classify_result(value="## 600519 收盘价 1680.0") == "ok"


def test_classify_ok_non_string_value():
    # 有的 vendor 返回 dict/DataFrame,非哨兵即视为成功
    assert classify_result(value={"close": 1.0}) == "ok"


def test_classify_no_data_sentinel_prefix():
    assert classify_result(value="NO_DATA_AVAILABLE: no rows") == "no_data"


def test_classify_no_data_from_exception():
    assert classify_result(exc=NoMarketDataError("510300.SS")) == "no_data"


def test_classify_no_data_news_error_sentinel():
    assert classify_result(value="Error fetching news for X") == "no_data"


def test_classify_no_perm_from_exception():
    assert classify_result(exc=VendorNotConfiguredError("no token")) == "no_perm"


def test_classify_no_perm_from_keyword():
    assert classify_result(value="抱歉,您的积分不足,无法访问该接口") == "no_perm"


def test_classify_unavailable_rate_limit():
    assert classify_result(exc=VendorRateLimitError("429")) == "unavailable"


def test_classify_unavailable_sentinel_prefix():
    assert classify_result(value="DATA_SOURCE_UNAVAILABLE: host down") == "unavailable"


def test_classify_unavailable_generic_exception():
    assert classify_result(exc=RuntimeError("boom")) == "unavailable"


def test_classify_sentinel_wins_over_keyword():
    # NO_DATA 前缀即使文本里含 "premium" 也判 no_data(前缀优先)
    assert classify_result(value="NO_DATA_AVAILABLE: premium only") == "no_data"


def test_count_probes_matches_matrix():
    from tradingagents.dataflows.diagnostics import count_probes
    from tradingagents.dataflows.interface import VENDOR_METHODS

    assert count_probes() == sum(len(v) for v in VENDOR_METHODS.values())


def test_iter_probes_covers_every_cell(monkeypatch):
    from tradingagents.dataflows.diagnostics import count_probes, iter_probes
    from tradingagents.dataflows.interface import VENDOR_METHODS

    # 桩掉每个 vendor,避免真实联网(单元测试不联网)
    for vendors in VENDOR_METHODS.values():
        for vendor in vendors:
            monkeypatch.setitem(vendors, vendor, lambda *a, **k: "stub")

    cells = list(iter_probes("510300.SS", "2026-07-13"))
    assert len(cells) == count_probes()
    # 每格都有分区与耗时
    assert all(c.group for c in cells)
    assert all(c.elapsed_ms >= 0 for c in cells)


def test_probe_cell_ok(monkeypatch):
    from tradingagents.dataflows import diagnostics
    from tradingagents.dataflows.interface import VENDOR_METHODS

    monkeypatch.setitem(
        VENDOR_METHODS["get_etf_profile"], "tushare", lambda *a, **k: "## 招商中证白酒"
    )
    cell = diagnostics.probe_cell("get_etf_profile", "tushare", "510300.SS", "2026-07-13")
    assert cell.status == "ok"
    assert cell.error_type is None
    assert "白酒" in cell.raw
    assert cell.group == "ETF 核心"


def test_probe_cell_no_perm_from_exception(monkeypatch):
    from tradingagents.dataflows import diagnostics
    from tradingagents.dataflows.errors import VendorNotConfiguredError
    from tradingagents.dataflows.interface import VENDOR_METHODS

    def _raise(*a, **k):
        raise VendorNotConfiguredError("missing token")

    monkeypatch.setitem(VENDOR_METHODS["get_etf_profile"], "tushare", _raise)
    cell = diagnostics.probe_cell("get_etf_profile", "tushare", "510300.SS", "2026-07-13")
    assert cell.status == "no_perm"
    assert cell.error_type == "VendorNotConfiguredError"


def test_probe_cell_never_raises(monkeypatch):
    from tradingagents.dataflows import diagnostics
    from tradingagents.dataflows.interface import VENDOR_METHODS

    def _boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(VENDOR_METHODS["get_etf_profile"], "tushare", _boom)
    cell = diagnostics.probe_cell("get_etf_profile", "tushare", "510300.SS", "2026-07-13")
    assert cell.status == "unavailable"
    assert "kaboom" in cell.raw


def test_probe_cell_non_symbol_method_gets_fixed_args(monkeypatch):
    from tradingagents.dataflows import diagnostics
    from tradingagents.dataflows.interface import VENDOR_METHODS

    seen = {}

    def _spy(*args, **kwargs):
        seen["args"] = args
        return "ok text"

    monkeypatch.setitem(VENDOR_METHODS["get_prediction_markets"], "polymarket", _spy)
    cell = diagnostics.probe_cell(
        "get_prediction_markets", "polymarket", "510300.SS", "2026-07-13"
    )
    # prediction markets 与具体 ETF 无关:不注入 code
    assert "510300.SS" not in [str(a) for a in seen["args"]]
    assert cell.group == "参考·与 ETF 无关"


def test_iter_probes_is_read_only(monkeypatch):
    # 遍历(所有格子用不联网的桩)不得改动全局 config
    from tradingagents.dataflows import diagnostics
    from tradingagents.dataflows.config import get_config
    from tradingagents.dataflows.interface import VENDOR_METHODS

    for vendors in VENDOR_METHODS.values():
        for vendor in vendors:
            monkeypatch.setitem(vendors, vendor, lambda *a, **k: "stub")

    before = dict(get_config())
    list(diagnostics.iter_probes("510300.SS", "2026-07-13"))
    assert dict(get_config()) == before


def test_method_desc_covers_every_method():
    from tradingagents.dataflows.diagnostics import METHOD_DESC, METHOD_GROUP

    assert set(METHOD_DESC) == set(METHOD_GROUP)
    assert all(METHOD_DESC[m].strip() for m in METHOD_GROUP)


def test_count_probes_with_vendors_subset():
    from tradingagents.dataflows.diagnostics import count_probes
    from tradingagents.dataflows.interface import VENDOR_METHODS

    only_tushare = sum(1 for vs in VENDOR_METHODS.values() if "tushare" in vs)
    assert count_probes(vendors={"tushare"}) == only_tushare
    assert count_probes(vendors=None) == count_probes()
    assert count_probes(vendors=set()) == 0


def test_iter_probes_filters_by_vendor(monkeypatch):
    from tradingagents.dataflows.diagnostics import iter_probes
    from tradingagents.dataflows.interface import VENDOR_METHODS

    for vendors in VENDOR_METHODS.values():
        for vendor in vendors:
            monkeypatch.setitem(vendors, vendor, lambda *a, **k: "stub")

    cells = list(iter_probes("510300.SS", "2026-07-13", vendors={"tushare"}))
    assert cells, "至少应有若干 tushare 格子"
    assert {c.vendor for c in cells} == {"tushare"}
    assert list(iter_probes("510300.SS", "2026-07-13", vendors=set())) == []


def test_build_meta_shape():
    from tradingagents.dataflows.diagnostics import build_meta
    from tradingagents.dataflows.interface import VENDOR_METHODS

    meta = build_meta()
    expected_vendors = sorted({v for vs in VENDOR_METHODS.values() for v in vs})
    assert meta["vendors"] == expected_vendors
    names = [m["name"] for m in meta["methods"]]
    assert set(names) == set(VENDOR_METHODS)
    assert all(m["desc"].strip() and m["group"] for m in meta["methods"])
