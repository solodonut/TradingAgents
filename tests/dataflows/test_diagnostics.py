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
