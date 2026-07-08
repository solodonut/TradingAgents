from tradingagents.dataflows.tushare_utils import resolve_symbol_type


def test_resolve_symbol_type_etf_vs_stock():
    assert resolve_symbol_type("510300.SS") == "etf"
    assert resolve_symbol_type("159915.SZ") == "etf"
    assert resolve_symbol_type("600519.SS") == "stock"
    assert resolve_symbol_type("000001.SZ") == "stock"
