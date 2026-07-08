import pandas as pd
import pytest

from tradingagents.dataflows import tushare_intraday
from tradingagents.dataflows.errors import NoMarketDataError


def _fake_frame():
    return pd.DataFrame(
        {
            "ts_code": ["510300.SH", "510300.SH"],
            "trade_time": ["2026-07-07 09:35:00", "2026-07-07 09:30:00"],
            "close": [4.859, 4.856],
            "vol": [25748316.0, 4182100.0],
        }
    )


def test_get_etf_intraday_returns_sorted_points(monkeypatch):
    monkeypatch.setattr(
        tushare_intraday, "_fetch_mins", lambda ts_code, trade_date, freq: _fake_frame()
    )
    out = tushare_intraday.get_etf_intraday("510300.SS", "2026-07-07", freq="5min")
    assert out["trade_date"] == "2026-07-07"
    assert out["freq"] == "5min"
    assert [p["t"] for p in out["points"]] == ["09:30", "09:35"]  # 升序
    assert out["points"][0]["price"] == 4.856


def test_get_etf_intraday_empty_raises(monkeypatch):
    monkeypatch.setattr(
        tushare_intraday, "_fetch_mins", lambda ts_code, trade_date, freq: pd.DataFrame()
    )
    with pytest.raises(NoMarketDataError):
        tushare_intraday.get_etf_intraday("510300.SS", "2026-07-07")


def _fake_daily():
    return pd.DataFrame(
        {
            "trade_date": ["20260707", "20260704"],
            "open": [4.86, 4.80],
            "high": [4.88, 4.85],
            "low": [4.85, 4.79],
            "close": [4.826, 4.83],
            "vol": [100.0, 90.0],
        }
    )


def test_get_etf_daily_kline_sorted_ascending(monkeypatch):
    monkeypatch.setattr(
        tushare_intraday, "_fetch_daily_raw", lambda ts_code, start, end: _fake_daily()
    )
    out = tushare_intraday.get_etf_daily_kline("510300.SS", "2026-07-07", lookback=60)
    dates = [k["date"] for k in out["kline"]]
    assert dates == ["2026-07-04", "2026-07-07"]
    assert out["kline"][-1]["c"] == 4.826
