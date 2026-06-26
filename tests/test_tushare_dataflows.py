from __future__ import annotations

from unittest import mock

import pandas as pd
import pytest

from tradingagents.dataflows import tushare_utils
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import VendorNotConfiguredError, VendorRateLimitError


@pytest.mark.unit
def test_tushare_client_requires_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    tushare_utils.reset_tushare_client()

    with pytest.raises(VendorNotConfiguredError):
        tushare_utils.get_tushare_client()


@pytest.mark.unit
def test_tushare_client_uses_env_token_without_logging_it(monkeypatch):
    client = object()
    set_token = mock.Mock()
    pro_api = mock.Mock(return_value=client)
    monkeypatch.setenv("TUSHARE_TOKEN", " secret-token ")
    monkeypatch.setattr(tushare_utils.ts, "set_token", set_token)
    monkeypatch.setattr(tushare_utils.ts, "pro_api", pro_api)
    tushare_utils.reset_tushare_client()

    assert tushare_utils.get_tushare_client() is client

    set_token.assert_called_once_with("secret-token")
    pro_api.assert_called_once_with()


@pytest.mark.unit
def test_tushare_call_maps_permission_message_to_rate_limit():
    def _missing_permission():
        raise Exception("抱歉，您没有访问该接口的权限，积分不足")

    with pytest.raises(VendorRateLimitError):
        tushare_utils.call_tushare(_missing_permission)


@pytest.mark.unit
def test_tushare_call_does_not_swallow_programmer_errors():
    def _bug():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        tushare_utils.call_tushare(_bug)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("600519.SS", "600519.SH"),
        ("000001.SZ", "000001.SZ"),
        ("430047.BJ", "430047.BJ"),
        ("430047", "430047.BJ"),
    ],
)
def test_to_ts_code_normalizes_mainland_exchange_suffixes(symbol, expected):
    assert tushare_utils.to_ts_code(symbol) == expected


@pytest.mark.unit
def test_tushare_cached_call_round_trips_dataframe(tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    calls = 0
    expected = pd.DataFrame({"ts_code": ["600519.SH"], "close": [1688.0]})

    def _fetch():
        nonlocal calls
        calls += 1
        return expected

    first = tushare_utils.cached_call("daily/600519.SH", 3600, _fetch)
    second = tushare_utils.cached_call("daily/600519.SH", 3600, _fetch)

    assert calls == 1
    pd.testing.assert_frame_equal(first, expected)
    pd.testing.assert_frame_equal(second, expected)


@pytest.mark.unit
def test_tushare_stock_normalizes_fund_daily(monkeypatch):
    from tradingagents.dataflows import tushare_stock

    client = mock.Mock()
    raw = pd.DataFrame(
        {
            "trade_date": ["20260619"],
            "open": [1.23],
            "high": [1.25],
            "low": [1.21],
            "close": [1.24],
            "vol": [123456.0],
            "amount": [45678.9],
        }
    )
    client.fund_daily.return_value = raw
    monkeypatch.setattr(tushare_stock, "get_tushare_client", mock.Mock(return_value=client))
    monkeypatch.setattr(tushare_stock, "call_tushare", lambda func: func())
    monkeypatch.setattr(tushare_stock, "cached_call", lambda key, ttl, func: func())

    result = tushare_stock.get_stock_data("159241", "2026-06-01", "2026-06-20")

    assert "Stock data for 159241.SZ (Tushare Pro)" in result
    assert "Date,Open,High,Low,Close,Volume,Amount" in result
    assert "2026-06-19,1.23,1.25,1.21,1.24,123456.0,45678.9" in result
    client.fund_daily.assert_called_once_with(
        ts_code="159241.SZ",
        start_date="20260601",
        end_date="20260620",
    )


@pytest.mark.unit
def test_tushare_stock_normalizes_a_share_daily(monkeypatch):
    from tradingagents.dataflows import tushare_stock

    client = mock.Mock()
    raw = pd.DataFrame(
        {
            "trade_date": ["20260619"],
            "open": [1680.0],
            "high": [1701.5],
            "low": [1678.25],
            "close": [1699.0],
            "vol": [98765.0],
            "amount": [1234567.89],
        }
    )
    client.daily.return_value = raw
    monkeypatch.setattr(tushare_stock, "get_tushare_client", mock.Mock(return_value=client))
    monkeypatch.setattr(tushare_stock, "call_tushare", lambda func: func())
    monkeypatch.setattr(tushare_stock, "cached_call", lambda key, ttl, func: func())

    result = tushare_stock.get_stock_data("600519", "2026-06-01", "2026-06-20")

    assert "Stock data for 600519.SS (Tushare Pro)" in result
    assert "Date,Open,High,Low,Close,Volume,Amount" in result
    assert "2026-06-19,1680.0,1701.5,1678.25,1699.0,98765.0,1234567.89" in result
    client.daily.assert_called_once_with(
        ts_code="600519.SH",
        start_date="20260601",
        end_date="20260620",
    )
