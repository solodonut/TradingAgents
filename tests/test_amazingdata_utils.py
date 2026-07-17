"""AmazingData 桥接层单元测试:错误分类、缓存毒化防护、记录抽取、字段映射。

在 ``ad_service_client`` 边界打桩,不触网。遵循现有约定(mocked, @pytest.mark.unit)。
"""

from unittest import mock

import pandas as pd
import pytest

from tradingagents.dataflows import amazingdata_utils as u
from tradingagents.dataflows.amazingdata_capital import _project as capital_project
from tradingagents.dataflows.amazingdata_etf import _freq_to_period
from tradingagents.dataflows.amazingdata_fundamentals import _prepare_frame, _project
from tradingagents.dataflows.amazingdata_stock import _extract_records, _normalize_frame

pytestmark = pytest.mark.unit


# ---- call_amazingdata 错误分类 -----------------------------------------


def _patch_service(available: bool, call_side_effect=None):
    svc = mock.MagicMock()
    svc.service_available.return_value = available
    if call_side_effect is not None:
        svc.call.side_effect = call_side_effect
    else:
        svc.call.return_value = {"meta": {"rows": 1}, "data": [{"x": 1}]}
    return mock.patch.object(u, "ad_service_client", svc)


def test_offline_raises_not_configured():
    with _patch_service(available=False), pytest.raises(u.AmazingdataNotConfiguredError):
        u.call_amazingdata("/kline")


def test_http_401_maps_to_not_configured():
    with _patch_service(True, RuntimeError("HTTP 401: invalid or missing X-API-Token")), \
            pytest.raises(u.AmazingdataNotConfiguredError):
        u.call_amazingdata("/kline")


def test_http_502_maps_to_rate_limit():
    with _patch_service(True, RuntimeError("HTTP 502: sdk exploded")), \
            pytest.raises(u.AmazingdataRateLimitError):
        u.call_amazingdata("/kline")


def test_http_403_connect_failed_maps_to_rate_limit():
    # 银河后端暂时断连,服务端以 403 抛 "Connect failed";必须优雅回退而非 crash。
    with _patch_service(True, RuntimeError("HTTP 403: Connect failed")), \
            pytest.raises(u.AmazingdataRateLimitError):
        u.call_amazingdata("/kline")


def test_http_403_method_not_allowed_is_not_swallowed():
    # 白名单违规是编程 bug,应原样抛出以便开发期暴露(不吞成 vendor 错误)。
    err = RuntimeError("HTTP 403: method not allowed")
    with _patch_service(True, err), pytest.raises(RuntimeError) as exc:
        u.call_amazingdata("/call")
    assert not isinstance(exc.value, (u.AmazingdataNotConfiguredError, u.AmazingdataRateLimitError))


def test_connection_error_after_probe_maps_to_not_configured():
    with _patch_service(True, ConnectionError("connection reset")), \
            pytest.raises(u.AmazingdataNotConfiguredError):
        u.call_amazingdata("/kline")


# ---- cached_call 毒化防护 ----------------------------------------------


def test_cached_call_does_not_persist_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(u, "_cache_dir", lambda: str(tmp_path))
    empty = {"meta": {"rows": 0}, "data": {}}
    calls = {"n": 0}

    def _fetch():
        calls["n"] += 1
        return empty

    u.cached_call("k", 9999, _fetch)
    u.cached_call("k", 9999, _fetch)
    assert calls["n"] == 2  # 空响应未落盘,两次都重新拉取
    assert not list(tmp_path.iterdir())


def test_cached_call_persists_nonempty(tmp_path, monkeypatch):
    monkeypatch.setattr(u, "_cache_dir", lambda: str(tmp_path))
    payload = {"meta": {"rows": 2}, "data": [{"a": 1}]}
    calls = {"n": 0}

    def _fetch():
        calls["n"] += 1
        return payload

    assert u.cached_call("k", 9999, _fetch) == payload
    assert u.cached_call("k", 9999, _fetch) == payload
    assert calls["n"] == 1  # 第二次命中缓存


# ---- _extract_records 兼容 dict[code] 与 list -------------------------


def test_extract_records_dict_by_code():
    resp = {"data": {"600519.SH": [{"a": 1}]}}
    assert _extract_records(resp, "600519.SH") == [{"a": 1}]


def test_extract_records_single_dict_fallback():
    resp = {"data": {"OTHER": [{"a": 1}]}}
    assert _extract_records(resp, "600519.SH") == [{"a": 1}]


def test_extract_records_list_shape():
    resp = {"data": [{"a": 1}, {"a": 2}]}
    assert _extract_records(resp, "600519.SH") == [{"a": 1}, {"a": 2}]


def test_extract_records_missing():
    assert _extract_records({"data": None}, "x") == []
    assert _extract_records({}, "x") == []


# ---- 行情字段映射 ------------------------------------------------------


def test_normalize_frame_maps_kline_columns():
    raw = pd.DataFrame([
        {"code": "600519.SH", "kline_time": 20260710, "open": 1.0, "high": 2.0,
         "low": 0.5, "close": 1.5, "volume": 100, "amount": 150.0},
        {"code": "600519.SH", "kline_time": 20260709, "open": 1.1, "high": 2.1,
         "low": 0.6, "close": 1.6, "volume": 110, "amount": 160.0},
    ])
    out = _normalize_frame(raw)
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume", "Amount"]
    assert str(out.index[0].date()) == "2026-07-09"  # 已按日期升序
    assert out.index.name == "Date"


# ---- 财务:合并报表优选 + look-ahead + 去重 ----------------------------


def _income_records():
    return [
        # 同一报告期两种 statement type,合并报表(=="1")营收更大
        {"REPORTING_PERIOD": "20251231", "ACTUAL_ANN_DATE": "20260417",
         "STATEMENT_TYPE": "1", "TOT_OPERA_REV": 172.0, "SECURITY_NAME": "贵州茅台"},
        {"REPORTING_PERIOD": "20251231", "ACTUAL_ANN_DATE": "20260417",
         "STATEMENT_TYPE": "2", "TOT_OPERA_REV": 41.0, "SECURITY_NAME": "贵州茅台"},
        # 未来公告日,应被 look-ahead 过滤
        {"REPORTING_PERIOD": "20260331", "ACTUAL_ANN_DATE": "20260425",
         "STATEMENT_TYPE": "1", "TOT_OPERA_REV": 54.0, "SECURITY_NAME": "贵州茅台"},
    ]


def test_prepare_frame_prefers_consolidated_and_filters_lookahead():
    df = _prepare_frame(_income_records(), curr_date="2026-04-20")
    # 只剩 20251231 合并报表本期(未来 20260331 被过滤;母公司行被去掉)
    assert len(df) == 1
    assert df.iloc[0]["REPORTING_PERIOD"] == "20251231"
    assert df.iloc[0]["TOT_OPERA_REV"] == 172.0


def test_prepare_frame_dedup_keeps_one_per_period():
    df = _prepare_frame(_income_records(), curr_date=None)
    assert df["REPORTING_PERIOD"].is_unique


def test_project_maps_labels_and_formats_dates():
    df = _prepare_frame(_income_records(), curr_date=None)
    from tradingagents.dataflows.amazingdata_fundamentals import _INCOME_FIELDS
    out = _project(df, _INCOME_FIELDS)
    assert "营业总收入" in out.columns
    assert "报告期" in out.columns
    # 日期格式化为 YYYY-MM-DD
    assert out["报告期"].iloc[0] == "2026-03-31"


def test_project_skips_absent_fields():
    df = pd.DataFrame([{"TOT_OPERA_REV": 1.0}])
    from tradingagents.dataflows.amazingdata_fundamentals import _INCOME_FIELDS
    out = _project(df, _INCOME_FIELDS)
    assert list(out.columns) == ["营业总收入"]  # 缺失字段被跳过


# ---- 资金面日期投影 + intraday 周期映射 --------------------------------


def test_capital_project_formats_trade_date():
    df = pd.DataFrame([{"TRADE_DATE": "20260710", "BORROW_MONEY_BALANCE": 1.0}])
    from tradingagents.dataflows.amazingdata_capital import _MARGIN_FIELDS
    out = capital_project(df, _MARGIN_FIELDS)
    assert out["交易日"].iloc[0] == "2026-07-10"
    assert out["融资余额"].iloc[0] == 1.0


@pytest.mark.parametrize("freq,period", [
    ("5min", "min5"), ("15min", "min15"), ("30min", "min30"), ("day", "day"),
])
def test_freq_to_period(freq, period):
    assert _freq_to_period(freq) == period
