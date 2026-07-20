"""Tests for the deterministic market-data verification snapshot (#830/#881)."""

from __future__ import annotations

import pandas as pd
import pytest

import tradingagents.dataflows.market_data_validator as validator


def _sample_ohlcv() -> pd.DataFrame:
    dates = pd.bdate_range("2026-04-01", "2026-05-20")
    closes = [100 + i for i in range(len(dates))]
    return pd.DataFrame({
        "Date": dates,
        "Open": [c - 0.5 for c in closes],
        "High": [c + 1.0 for c in closes],
        "Low": [c - 1.0 for c in closes],
        "Close": closes,
        "Volume": [1_000_000 + i for i in range(len(dates))],
    })


@pytest.mark.unit
class TestVerifiedSnapshot:
    def test_mainland_snapshot_falls_back_amazingdata_tushare_akshare(
        self, monkeypatch
    ):
        calls = []

        def _fail(source, exc):
            def _loader(symbol, curr_date):
                calls.append(source)
                raise exc

            return _loader

        def _akshare(symbol, curr_date):
            calls.append("AKShare")
            return _sample_ohlcv()

        monkeypatch.setattr(
            validator,
            "_load_amazingdata_ohlcv",
            _fail("AmazingData", ConnectionError("AmazingData unavailable")),
            raising=False,
        )
        monkeypatch.setattr(
            validator,
            "_load_tushare_ohlcv",
            _fail("Tushare", ConnectionError("Tushare unavailable")),
            raising=False,
        )
        monkeypatch.setattr(validator, "_load_akshare_ohlcv", _akshare, raising=False)
        monkeypatch.setattr(
            validator,
            "load_ohlcv",
            lambda *_: pytest.fail("mainland snapshot must use the explicit vendor chain"),
        )

        snap = validator.build_verified_market_snapshot("159248", "2026-05-20")

        assert calls == ["AmazingData", "Tushare", "AKShare"]
        assert "Data source used: AKShare" in snap

    def test_mainland_snapshot_stops_after_tushare_success(self, monkeypatch):
        calls = []

        def _amazingdata(symbol, curr_date):
            calls.append("AmazingData")
            raise ConnectionError("AmazingData unavailable")

        def _tushare(symbol, curr_date):
            calls.append("Tushare")
            return _sample_ohlcv()

        def _akshare(symbol, curr_date):
            calls.append("AKShare")
            pytest.fail("AKShare must not run after Tushare succeeds")

        monkeypatch.setattr(
            validator, "_load_amazingdata_ohlcv", _amazingdata, raising=False
        )
        monkeypatch.setattr(
            validator, "_load_tushare_ohlcv", _tushare, raising=False
        )
        monkeypatch.setattr(validator, "_load_akshare_ohlcv", _akshare, raising=False)

        snap = validator.build_verified_market_snapshot("159248", "2026-05-20")

        assert calls == ["AmazingData", "Tushare"]
        assert "Data source used: Tushare" in snap

    def test_excludes_future_rows(self, monkeypatch):
        data = pd.concat([
            _sample_ohlcv(),
            pd.DataFrame({"Date": [pd.Timestamp("2026-06-01")], "Open": [999.0],
                          "High": [999.0], "Low": [999.0], "Close": [999.0], "Volume": [999]}),
        ], ignore_index=True)
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: data)

        snap = validator.build_verified_market_snapshot("COF", "2026-05-13")
        assert "Verified market data snapshot for COF" in snap
        assert "Requested analysis date: 2026-05-13" in snap
        assert "Latest trading row used: 2026-05-13" in snap
        assert "999.00" not in snap          # future row excluded
        assert "boll_lb" in snap             # indicators present

    def test_uses_previous_trading_day_when_date_is_weekend(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: _sample_ohlcv())
        # 2026-05-16 is a Saturday; latest row should be Fri 2026-05-15
        snap = validator.build_verified_market_snapshot("COF", "2026-05-16")
        assert "Latest trading row used: 2026-05-15" in snap
        assert "Recent verified closes" in snap

    def test_raises_when_no_rows_on_or_before_date(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: _sample_ohlcv())
        with pytest.raises(ValueError):
            validator.build_verified_market_snapshot("COF", "2020-01-01")

    def test_raises_on_empty_data(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: pd.DataFrame())
        with pytest.raises(ValueError):
            validator.build_verified_market_snapshot("COF", "2026-05-13")

    def test_look_back_window_capped_at_30(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: _sample_ohlcv())
        snap = validator.build_verified_market_snapshot("COF", "2026-05-20", look_back_days=999)
        # last-N closes table has at most 30 data rows
        close_rows = [ln for ln in snap.splitlines() if ln.startswith("| 2026-")]
        assert 0 < len(close_rows) <= 30


@pytest.mark.unit
class TestTool:
    def test_tool_delegates_to_builder(self, monkeypatch):
        from tradingagents.agents.utils.market_data_validation_tools import (
            get_verified_market_snapshot,
        )
        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: _sample_ohlcv())
        out = get_verified_market_snapshot.invoke(
            {"symbol": "COF", "curr_date": "2026-05-20"}
        )
        assert "Verified market data snapshot for COF" in out

    def test_tool_returns_sentinel_on_network_error(self, monkeypatch):
        """Network failure across the snapshot chain must not crash the run.

        Without the tool-boundary catch this raises ConnectionError, which
        propagates through the LangGraph ToolNode and aborts the whole run via
        api/runner.py (#route-to-vendor-network-error-crash, on the snapshot path).
        """
        import requests

        from tradingagents.agents.utils.market_data_validation_tools import (
            get_verified_market_snapshot,
        )

        def _boom(symbol, curr_date):
            raise requests.exceptions.ConnectionError("Remote end closed connection")

        monkeypatch.setattr(validator, "_load_amazingdata_ohlcv", _boom)
        monkeypatch.setattr(validator, "_load_tushare_ohlcv", _boom)
        monkeypatch.setattr(validator, "_load_akshare_ohlcv", _boom)
        out = get_verified_market_snapshot.invoke(
            {"symbol": "159241", "curr_date": "2026-06-25"}
        )
        assert "MARKET_SNAPSHOT_UNAVAILABLE" in out
        assert "ConnectionError" in out
        assert "do not fabricate" in out.lower()

    def test_tool_returns_sentinel_on_no_data(self, monkeypatch):
        from tradingagents.agents.utils.market_data_validation_tools import (
            get_verified_market_snapshot,
        )

        monkeypatch.setattr(validator, "load_ohlcv", lambda s, d: pd.DataFrame())
        out = get_verified_market_snapshot.invoke(
            {"symbol": "COF", "curr_date": "2026-05-13"}
        )
        assert "MARKET_SNAPSHOT_UNAVAILABLE" in out
