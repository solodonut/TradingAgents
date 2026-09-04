import json
import pathlib

# 腾讯/新浪探针的 fixture 与 vendor 单测共用同一份 2026-09-04 真实响应,
# 免得健康检查这边照抄一串 88 字段的假数据、和上游真实形状悄悄走偏。
_VENDOR_FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "dataflows" / "fixtures"

# 只启用被探的那一家,其余服务落到 disabled 分支,测试不会触网。
_TENCENT_ONLY = {"tool_vendors": {"get_etf_realtime": "tencent"}}
_SINA_ONLY = {"tool_vendors": {"get_global_news": "sina"}}


def _sse_events(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    current_event: str | None = None
    current_data: str | None = None
    for line in body.splitlines():
        if line.startswith("event: "):
            current_event = line.removeprefix("event: ")
        elif line.startswith("data: "):
            current_data = line.removeprefix("data: ")
        elif line == "" and current_event and current_data:
            events.append((current_event, json.loads(current_data)))
            current_event = None
            current_data = None
    return events


def test_service_health_stream_emits_progress_and_summary(client, monkeypatch):
    import api.service_health as service_health

    def fake_llm_probe(config):
        yield {
            "id": "llm:deep_think_llm:fast-model",
            "name": "Deep LLM: fast-model",
            "kind": "llm",
            "status": "checking",
            "message": "Checking model",
            "latency_ms": None,
        }
        yield {
            "id": "llm:deep_think_llm:fast-model",
            "name": "Deep LLM: fast-model",
            "kind": "llm",
            "status": "ok",
            "message": "Reachable",
            "latency_ms": 12,
        }

    def fake_data_probe(config):
        yield {
            "id": "data:eastmoney",
            "name": "Eastmoney 直连",
            "kind": "data",
            "status": "ok",
            "message": "Reachable",
            "latency_ms": 7,
        }
        yield {
            "id": "data:fred",
            "name": "FRED",
            "kind": "data",
            "status": "disabled",
            "message": "Disabled by current configuration",
            "latency_ms": None,
        }

    monkeypatch.setattr(service_health, "_probe_llm_services", fake_llm_probe)
    monkeypatch.setattr(service_health, "_probe_data_services", fake_data_probe)

    with client.stream("GET", "/api/health/services/stream") as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    events = _sse_events(body)
    assert [event for event, _data in events] == [
        "service_status",
        "service_status",
        "service_status",
        "service_status",
        "summary",
    ]
    summary = events[-1][1]
    assert summary["ok"] == 2
    assert summary["disabled"] == 1
    assert summary["error"] == 0


def test_service_health_stream_counts_warning_status(client, monkeypatch):
    import api.service_health as service_health

    monkeypatch.setattr(service_health, "_probe_llm_services", lambda config: iter(()))

    def fake_data_probe(config):
        yield {
            "id": "data:eastmoney",
            "name": "Eastmoney 直连",
            "kind": "data",
            "status": "warning",
            "message": "Reachable, but latest daily data is 2026-07-08; expected 2026-07-09",
            "latency_ms": 7,
        }

    monkeypatch.setattr(service_health, "_probe_data_services", fake_data_probe)

    with client.stream("GET", "/api/health/services/stream") as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    events = _sse_events(body)
    summary = events[-1][1]
    assert summary["warning"] == 1
    assert summary["error"] == 0


def test_service_health_stream_reports_internal_probe_error(client, monkeypatch):
    import api.service_health as service_health

    def broken_llm_probe(config):
        raise RuntimeError("probe exploded")
        yield

    monkeypatch.setattr(service_health, "_probe_llm_services", broken_llm_probe)
    monkeypatch.setattr(service_health, "_probe_data_services", lambda config: iter(()))

    with client.stream("GET", "/api/health/services/stream") as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    events = _sse_events(body)
    assert events[0][0] == "service_status"
    assert events[0][1]["id"] == "health:internal"
    assert events[0][1]["status"] == "error"
    assert "probe exploded" in events[0][1]["message"]
    assert events[-1][0] == "summary"
    assert events[-1][1]["error"] == 1


def test_single_service_health_returns_requested_status(client, monkeypatch):
    import api.service_health as service_health

    def fake_llm_probe(config):
        yield {
            "id": "llm:deep_think_llm:fast-model",
            "name": "Deep LLM: fast-model",
            "kind": "llm",
            "status": "ok",
            "message": "Reachable",
            "latency_ms": 12,
        }

    def fake_data_probe(config):
        yield {
            "id": "data:eastmoney",
            "name": "Eastmoney 直连",
            "kind": "data",
            "status": "error",
            "message": "HTTP 503",
            "latency_ms": 55,
        }

    monkeypatch.setattr(service_health, "_probe_llm_services", fake_llm_probe)
    monkeypatch.setattr(service_health, "_probe_data_services", fake_data_probe)

    response = client.get("/api/health/services/data:eastmoney")

    assert response.status_code == 200
    assert response.json() == {
        "id": "data:eastmoney",
        "name": "Eastmoney 直连",
        "kind": "data",
        "status": "error",
        "message": "HTTP 503",
        "latency_ms": 55,
    }


def test_single_service_health_supports_slashes_in_service_id(client, monkeypatch):
    import api.service_health as service_health

    def fake_llm_probe(config):
        yield {
            "id": "llm:deep_think_llm:openrouter/anthropic/claude",
            "name": "Deep LLM: openrouter/anthropic/claude",
            "kind": "llm",
            "status": "ok",
            "message": "Reachable",
            "latency_ms": 34,
        }

    monkeypatch.setattr(service_health, "_probe_llm_services", fake_llm_probe)
    monkeypatch.setattr(service_health, "_probe_data_services", lambda config: iter(()))

    response = client.get("/api/health/services/llm:deep_think_llm:openrouter/anthropic/claude")

    assert response.status_code == 200
    assert response.json()["id"] == "llm:deep_think_llm:openrouter/anthropic/claude"


def test_single_service_health_returns_404_for_unknown_service(client, monkeypatch):
    import api.service_health as service_health

    monkeypatch.setattr(service_health, "_probe_llm_services", lambda config: iter(()))
    monkeypatch.setattr(service_health, "_probe_data_services", lambda config: iter(()))

    response = client.get("/api/health/services/data:missing")

    assert response.status_code == 404


def test_data_probe_marks_unconfigured_services_disabled(monkeypatch):
    import api.service_health as service_health

    monkeypatch.setattr(
        service_health, "_http_probe", lambda url, params=None, headers=None: (True, "ok", 1)
    )

    statuses = list(
        service_health._probe_data_services({"data_vendors": {"core_stock_apis": "tushare"}})
    )

    by_id = {item["id"]: item for item in statuses}
    assert by_id["data:yfinance"]["status"] == "disabled"
    assert by_id["data:fred"]["status"] == "disabled"
    assert by_id["data:polymarket"]["status"] == "disabled"


def test_data_probe_sends_browser_headers_for_eastmoney(monkeypatch):
    from api.service_health import _probe_data_services

    seen = {}

    def http_probe(url, params=None, headers=None):
        seen[url] = headers
        return True, "Reachable", 9

    monkeypatch.setattr("api.service_health._http_probe", http_probe)

    statuses = list(
        _probe_data_services({"tool_vendors": {"get_news": "eastmoney,tushare"}})
    )

    by_id = {item["id"]: item for item in statuses}
    assert by_id["data:eastmoney"]["name"] == "Eastmoney 直连"
    assert by_id["data:eastmoney"]["status"] == "ok"
    # search-api-web rejects requests without a browser UA + Referer.
    headers = seen["https://search-api-web.eastmoney.com/search/jsonp"]
    assert headers["Referer"] == "https://so.eastmoney.com/"
    assert "Mozilla" in headers["User-Agent"]


def test_data_probe_reports_missing_required_api_key(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

    statuses = list(
        _probe_data_services({"data_vendors": {"core_stock_apis": "alpha_vantage"}})
    )

    alpha = next(item for item in statuses if item["id"] == "data:alpha_vantage")
    assert alpha["status"] == "error"
    assert "ALPHA_VANTAGE_API_KEY" in alpha["message"]


def test_data_probe_reports_missing_tushare_token(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    statuses = list(
        _probe_data_services({"data_vendors": {"core_stock_apis": "tushare"}})
    )

    tushare = next(item for item in statuses if item["id"] == "data:tushare")
    assert tushare["status"] == "error"
    assert "TUSHARE_TOKEN" in tushare["message"]


def test_data_probe_reports_tushare_fresh_today(monkeypatch):
    from api.service_health import _probe_data_services

    calls = []
    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    monkeypatch.setattr("api.service_health._today_compact", lambda: "20260709")

    def json_probe(url, method="GET", params=None, json_payload=None, headers=None):
        calls.append(
            {
                "url": url,
                "method": method,
                "params": params,
                "json_payload": json_payload,
                "headers": headers,
            }
        )
        if len(calls) == 1:
            return True, {"data": {"items": [["20260709", 1]]}}, 12
        return True, {"data": {"items": [{"trade_date": "20260709"}]}}, 24

    monkeypatch.setattr("api.service_health._json_probe", json_probe)

    statuses = list(_probe_data_services({"data_vendors": {"core_stock_apis": "tushare"}}))

    tushare = next(item for item in statuses if item["id"] == "data:tushare")
    assert tushare["status"] == "ok"
    assert tushare["latency_ms"] == 36
    assert "latest daily data is 2026-07-09" in tushare["message"]
    assert len(calls) == 2
    assert calls[0]["method"] == "POST"
    assert calls[0]["json_payload"]["api_name"] == "trade_cal"
    assert calls[0]["json_payload"]["token"] == "token"
    assert calls[1]["method"] == "POST"
    assert calls[1]["json_payload"]["api_name"] == "daily"
    assert calls[1]["json_payload"]["token"] == "token"


def test_data_probe_reports_tushare_warning_when_stale(monkeypatch):
    from api.service_health import _probe_data_services

    calls = []
    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    monkeypatch.setattr("api.service_health._today_compact", lambda: "20260709")

    def json_probe(url, method="GET", params=None, json_payload=None, headers=None):
        calls.append(
            {
                "url": url,
                "method": method,
                "params": params,
                "json_payload": json_payload,
                "headers": headers,
            }
        )
        if len(calls) == 1:
            return True, {"data": {"items": [["20260709", 1]]}}, 12
        return True, {"data": {"items": [{"trade_date": "20260708"}]}}, 24

    monkeypatch.setattr("api.service_health._json_probe", json_probe)

    statuses = list(_probe_data_services({"data_vendors": {"core_stock_apis": "tushare"}}))

    tushare = next(item for item in statuses if item["id"] == "data:tushare")
    assert tushare["status"] == "warning"
    assert "latest daily data is 2026-07-08; expected 2026-07-09" in tushare["message"]
    assert len(calls) == 2
    assert calls[0]["method"] == "POST"
    assert calls[0]["json_payload"]["api_name"] == "trade_cal"
    assert calls[0]["json_payload"]["token"] == "token"
    assert calls[1]["method"] == "POST"
    assert calls[1]["json_payload"]["api_name"] == "daily"
    assert calls[1]["json_payload"]["token"] == "token"


def test_data_probe_does_not_run_freshness_after_reachability_failure(monkeypatch):
    from api.service_health import _probe_data_services

    calls = {"freshness": 0}
    monkeypatch.setenv("FRED_API_KEY", "token")
    monkeypatch.setattr(
        "api.service_health._http_probe",
        lambda url, params=None, headers=None: (False, "HTTP 503", 12),
    )

    def json_probe(*args, **kwargs):
        calls["freshness"] += 1
        return True, {"data": {"items": [{"trade_date": "20260709"}]}}, 24

    monkeypatch.setattr("api.service_health._json_probe", json_probe)

    statuses = list(_probe_data_services({"data_vendors": {"macro_data": "fred"}}))

    fred = next(item for item in statuses if item["id"] == "data:fred")
    assert fred["status"] == "error"
    assert fred["message"] == "HTTP 503"
    assert calls["freshness"] == 0


def test_data_probe_reports_yfinance_ok_when_fresh(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setattr("api.service_health._today_compact", lambda: "20260709")
    http_calls = {"count": 0}

    def http_probe(url, params=None, headers=None):
        http_calls["count"] += 1
        return True, "Reachable", 11

    monkeypatch.setattr("api.service_health._http_probe", http_probe)
    monkeypatch.setattr(
        "api.service_health._json_probe",
        lambda url, method="GET", params=None, json_payload=None, headers=None: (
            True,
            {"chart": {"result": [{"timestamp": [1783555200]}]}},
            19,
        ),
    )

    statuses = list(_probe_data_services({"data_vendors": {"core_stock_apis": "yfinance"}}))

    yahoo = next(item for item in statuses if item["id"] == "data:yfinance")
    assert yahoo["status"] == "ok"
    assert "latest daily data is 2026-07-09" in yahoo["message"]
    assert yahoo["latency_ms"] == 19
    assert http_calls["count"] == 0


def test_data_probe_reports_alpha_vantage_warning_when_stale(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "token")
    monkeypatch.setattr("api.service_health._today_compact", lambda: "20260709")
    monkeypatch.setattr(
        "api.service_health._http_probe",
        lambda url, params=None, headers=None: (True, "Reachable", 11),
    )
    monkeypatch.setattr(
        "api.service_health._json_probe",
        lambda url, method="GET", params=None, json_payload=None, headers=None: (
            True,
            {"Global Quote": {"07. latest trading day": "2026-07-08"}},
            17,
        ),
    )

    statuses = list(_probe_data_services({"data_vendors": {"core_stock_apis": "alpha_vantage"}}))

    alpha = next(item for item in statuses if item["id"] == "data:alpha_vantage")
    assert alpha["status"] == "warning"
    assert "latest daily data is 2026-07-08; expected 2026-07-09" in alpha["message"]


def test_data_probe_reports_fred_warning_when_stale(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setenv("FRED_API_KEY", "token")
    monkeypatch.setattr("api.service_health._today_compact", lambda: "20260709")
    monkeypatch.setattr(
        "api.service_health._http_probe",
        lambda url, params=None, headers=None: (True, "Reachable", 11),
    )
    monkeypatch.setattr(
        "api.service_health._json_probe",
        lambda url, method="GET", params=None, json_payload=None, headers=None: (
            True,
            {"observations": [{"date": "2026-07-08", "value": "4.12"}]},
            17,
        ),
    )

    statuses = list(_probe_data_services({"data_vendors": {"macro_data": "fred"}}))

    fred = next(item for item in statuses if item["id"] == "data:fred")
    assert fred["status"] == "warning"
    assert "latest daily data is 2026-07-08; expected 2026-07-09" in fred["message"]


def test_data_probe_reports_error_when_freshness_payload_has_no_date(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setenv("FRED_API_KEY", "token")
    monkeypatch.setattr(
        "api.service_health._http_probe",
        lambda url, params=None, headers=None: (True, "Reachable", 9),
    )
    monkeypatch.setattr(
        "api.service_health._json_probe",
        lambda url, method="GET", params=None, json_payload=None, headers=None: (
            True,
            {"data": {"items": []}},
            13,
        ),
    )

    statuses = list(_probe_data_services({"data_vendors": {"macro_data": "fred"}}))

    fred = next(item for item in statuses if item["id"] == "data:fred")
    assert fred["status"] == "error"
    assert fred["message"] == "Reachable, but freshness response had no usable date"


def test_data_probe_reports_amazingdata_ok_when_fresh(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setattr("api.service_health._today_compact", lambda: "20260709")
    monkeypatch.setattr(
        "tradingagents.dataflows.ad_service_client.service_available",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.ad_service_client.call",
        lambda *args, **kwargs: {
            "data": {"000001.SZ": [{"kline_time": 20260708}, {"kline_time": 20260709}]}
        },
    )

    statuses = list(
        _probe_data_services({"data_vendors": {"core_stock_apis": "amazingdata"}})
    )

    ad = next(item for item in statuses if item["id"] == "data:amazingdata")
    assert ad["status"] == "ok"
    assert "latest daily data is 2026-07-09" in ad["message"]
    assert ad["latency_ms"] is not None


def test_data_probe_reports_amazingdata_warning_when_stale(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setattr("api.service_health._today_compact", lambda: "20260709")
    monkeypatch.setattr(
        "tradingagents.dataflows.ad_service_client.service_available",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.ad_service_client.call",
        lambda *args, **kwargs: {"data": {"000001.SZ": [{"kline_time": 20260708}]}},
    )

    statuses = list(
        _probe_data_services({"data_vendors": {"core_stock_apis": "amazingdata"}})
    )

    ad = next(item for item in statuses if item["id"] == "data:amazingdata")
    assert ad["status"] == "warning"
    assert "latest daily data is 2026-07-08; expected 2026-07-09" in ad["message"]


def test_data_probe_reports_amazingdata_warning_when_no_date(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setattr(
        "tradingagents.dataflows.ad_service_client.service_available",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.ad_service_client.call",
        lambda *args, **kwargs: {"data": {"000001.SZ": []}},
    )

    statuses = list(
        _probe_data_services({"data_vendors": {"core_stock_apis": "amazingdata"}})
    )

    ad = next(item for item in statuses if item["id"] == "data:amazingdata")
    assert ad["status"] == "warning"
    assert "latest data date is unavailable" in ad["message"]


def test_data_probe_reports_amazingdata_warning_when_kline_fails(monkeypatch):
    from api.service_health import _probe_data_services

    def boom(*args, **kwargs):
        raise RuntimeError("HTTP 403: Connect failed")

    monkeypatch.setattr(
        "tradingagents.dataflows.ad_service_client.service_available",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr("tradingagents.dataflows.ad_service_client.call", boom)

    statuses = list(
        _probe_data_services({"data_vendors": {"core_stock_apis": "amazingdata"}})
    )

    ad = next(item for item in statuses if item["id"] == "data:amazingdata")
    assert ad["status"] == "warning"
    assert "latest data date is unavailable" in ad["message"]


def test_data_probe_reports_amazingdata_error_when_unavailable(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setattr(
        "tradingagents.dataflows.ad_service_client.service_available",
        lambda *args, **kwargs: False,
    )

    statuses = list(
        _probe_data_services({"data_vendors": {"core_stock_apis": "amazingdata"}})
    )

    ad = next(item for item in statuses if item["id"] == "data:amazingdata")
    assert ad["status"] == "error"


def test_data_probe_marks_amazingdata_disabled_without_probe(monkeypatch):
    from api.service_health import _probe_data_services

    def explode(*args, **kwargs):
        raise AssertionError("service_available must not run for a disabled vendor")

    monkeypatch.setattr(
        "tradingagents.dataflows.ad_service_client.service_available", explode
    )

    statuses = list(
        _probe_data_services({"data_vendors": {"core_stock_apis": "tushare"}})
    )

    ad = next(item for item in statuses if item["id"] == "data:amazingdata")
    assert ad["status"] == "disabled"


def test_data_probe_reports_tencent_ok_when_snapshot_is_today(monkeypatch):
    from api.service_health import _probe_data_services

    quote = (_VENDOR_FIXTURES / "tencent_quote_sh510300.txt").read_text(encoding="utf-8")
    seen = {}

    def text_probe(url, params=None, headers=None, encoding="utf-8"):
        seen["url"] = url
        seen["encoding"] = encoding
        return True, quote, 14

    monkeypatch.setattr("api.service_health._text_probe", text_probe)
    # fixture 的快照时间是 20260904103758。
    monkeypatch.setattr("api.service_health._today_compact", lambda: "20260904")

    statuses = list(_probe_data_services(_TENCENT_ONLY))

    tencent = next(item for item in statuses if item["id"] == "data:tencent")
    assert tencent["name"] == "腾讯行情 (IOPV)"
    assert tencent["status"] == "ok"
    assert "latest daily data is 2026-09-04" in tencent["message"]
    assert tencent["latency_ms"] == 14
    assert seen["url"] == "https://qt.gtimg.cn/q=sh510300"
    # 快照接口返回 GBK 且响应头不带 charset,猜错编码会把中文名变乱码。
    assert seen["encoding"] == "gbk"


def test_data_probe_reports_tencent_warning_when_snapshot_is_stale(monkeypatch):
    from api.service_health import _probe_data_services

    quote = (_VENDOR_FIXTURES / "tencent_quote_sh510300.txt").read_text(encoding="utf-8")
    monkeypatch.setattr(
        "api.service_health._text_probe",
        lambda url, params=None, headers=None, encoding="utf-8": (True, quote, 14),
    )
    monkeypatch.setattr("api.service_health._today_compact", lambda: "20260907")

    statuses = list(_probe_data_services(_TENCENT_ONLY))

    tencent = next(item for item in statuses if item["id"] == "data:tencent")
    assert tencent["status"] == "warning"
    assert "latest daily data is 2026-09-04; expected 2026-09-07" in tencent["message"]


def test_data_probe_reports_tencent_warning_when_iopv_is_zero(monkeypatch):
    from api.service_health import _probe_data_services

    quote = (_VENDOR_FIXTURES / "tencent_quote_sh510300.txt").read_text(encoding="utf-8")
    fields = quote.split('="', 1)[1].rstrip().rstrip(";").rstrip('"').split("~")
    fields[78] = "0.000"  # 停牌 / 上游异常时腾讯返回 0
    zeroed = f'v_sh510300="{"~".join(fields)}";\n'

    monkeypatch.setattr(
        "api.service_health._text_probe",
        lambda url, params=None, headers=None, encoding="utf-8": (True, zeroed, 14),
    )

    statuses = list(_probe_data_services(_TENCENT_ONLY))

    tencent = next(item for item in statuses if item["id"] == "data:tencent")
    assert tencent["status"] == "warning"
    assert "IOPV is missing or zero" in tencent["message"]


def test_data_probe_reports_tencent_error_when_fields_are_truncated(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setattr(
        "api.service_health._text_probe",
        lambda url, params=None, headers=None, encoding="utf-8": (
            True,
            'v_sh510300="1~沪深300ETF华泰柏瑞~510300~4.645";\n',
            14,
        ),
    )

    statuses = list(_probe_data_services(_TENCENT_ONLY))

    tencent = next(item for item in statuses if item["id"] == "data:tencent")
    assert tencent["status"] == "error"
    assert "expected at least 82" in tencent["message"]


def test_data_probe_reports_tencent_error_when_quote_is_empty(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setattr(
        "api.service_health._text_probe",
        lambda url, params=None, headers=None, encoding="utf-8": (True, 'v_sh510300="";\n', 14),
    )

    statuses = list(_probe_data_services(_TENCENT_ONLY))

    tencent = next(item for item in statuses if item["id"] == "data:tencent")
    assert tencent["status"] == "error"
    assert "rate-limited or blocked" in tencent["message"]


def test_data_probe_reports_sina_ok_and_sends_referer(monkeypatch):
    from api.service_health import _probe_data_services

    feed = (_VENDOR_FIXTURES / "sina_zhibo_feed.json").read_text(encoding="utf-8")
    seen = {}

    def text_probe(url, params=None, headers=None, encoding="utf-8"):
        seen["url"] = url
        seen["params"] = params
        seen["headers"] = headers
        return True, feed, 21

    monkeypatch.setattr("api.service_health._text_probe", text_probe)

    statuses = list(_probe_data_services(_SINA_ONLY))

    sina = next(item for item in statuses if item["id"] == "data:sina")
    assert sina["name"] == "新浪财经 7×24"
    assert sina["status"] == "ok"
    assert sina["message"] == "Reachable"
    assert seen["url"] == "https://zhibo.sina.com.cn/api/zhibo/feed"
    assert seen["params"]["zhibo_id"] == 152
    # 缺 Referer 新浪直接 403。
    assert seen["headers"]["Referer"] == "https://finance.sina.com.cn/"


def test_data_probe_reports_sina_warning_when_feed_is_empty(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setattr(
        "api.service_health._text_probe",
        lambda url, params=None, headers=None, encoding="utf-8": (
            True,
            json.dumps({"result": {"data": {"feed": {"list": []}}}}),
            21,
        ),
    )

    statuses = list(_probe_data_services(_SINA_ONLY))

    sina = next(item for item in statuses if item["id"] == "data:sina")
    assert sina["status"] == "warning"
    assert "returned no items" in sina["message"]


def test_data_probe_reports_sina_error_when_response_is_not_json(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setattr(
        "api.service_health._text_probe",
        lambda url, params=None, headers=None, encoding="utf-8": (True, "<html>403</html>", 21),
    )

    statuses = list(_probe_data_services(_SINA_ONLY))

    sina = next(item for item in statuses if item["id"] == "data:sina")
    assert sina["status"] == "error"
    assert sina["message"] == "Reachable, but the feed response was not JSON"


def test_data_probe_marks_tencent_and_sina_disabled_without_probe(monkeypatch):
    from api.service_health import _probe_data_services

    def explode(*args, **kwargs):
        raise AssertionError("_text_probe must not run for a disabled vendor")

    monkeypatch.setattr("api.service_health._text_probe", explode)

    statuses = list(_probe_data_services({"data_vendors": {"core_stock_apis": "yfinance"}}))

    by_id = {item["id"]: item for item in statuses}
    assert by_id["data:tencent"]["status"] == "disabled"
    assert by_id["data:sina"]["status"] == "disabled"


def test_text_probe_bypasses_proxy_configuration(monkeypatch):
    from api.service_health import _text_probe

    seen = {}

    class FakeResponse:
        status_code = 200
        encoding = None
        text = "ok"

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def get(self, url, params=None, headers=None, timeout=None):
            seen["trust_env"] = self.trust_env
            seen["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr("api.service_health.requests.Session", FakeSession)

    ok, text, _latency_ms = _text_probe("https://qt.gtimg.cn/q=sh510300")

    assert (ok, text) == (True, "ok")
    # 企业代理隧道不到境内主机;不绕过会让健康检查报红而实际取数是好的。
    assert seen["trust_env"] is False
    assert seen["timeout"] == 5


def test_freshness_status_reports_ok_for_today(monkeypatch):
    import api.service_health as service_health

    monkeypatch.setattr(service_health, "_today_compact", lambda: "20260709")

    status, message = service_health._freshness_status("20260709")

    assert status == "ok"
    assert message == "Reachable; latest daily data is 2026-07-09"


def test_freshness_status_reports_warning_for_stale_date(monkeypatch):
    import api.service_health as service_health

    monkeypatch.setattr(service_health, "_today_compact", lambda: "20260709")

    status, message = service_health._freshness_status("20260708")

    assert status == "warning"
    assert message == "Reachable, but latest daily data is 2026-07-08; expected 2026-07-09"


def test_extract_latest_date_handles_nested_vendor_payloads():
    from api.service_health import _extract_latest_date

    assert _extract_latest_date({"data": {"items": [{"trade_date": "20260708"}]}}) == "20260708"
    assert _extract_latest_date({"Time Series (Daily)": {"2026-07-09": {"4. close": "10"}}}) == "20260709"
    assert _extract_latest_date({"observations": [{"date": "2026-07-08"}]}) == "20260708"
    assert _extract_latest_date({"chart": {"result": [{"timestamp": [1783555200]}]}}) == "20260709"


def test_extract_latest_date_handles_tushare_fields_items_payload():
    from api.service_health import _extract_latest_date

    payload = {"data": {"fields": ["trade_date", "close"], "items": [["20260709", 10.0]]}}

    assert _extract_latest_date(payload) == "20260709"


def test_http_probe_redacts_secret_values_from_request_exceptions(monkeypatch):
    import requests

    from api.service_health import _http_probe

    def broken_get(*args, **kwargs):
        raise requests.exceptions.RequestException(
            "failed https://example.test/query?apikey=SECRET123&api_key=SECRET456&token=SECRET789"
        )

    monkeypatch.setattr("api.service_health.requests.get", broken_get)

    ok, message, _latency_ms = _http_probe(
        "https://example.test/query",
        params={"apikey": "SECRET123", "api_key": "SECRET456", "token": "SECRET789"},
    )

    assert ok is False
    assert "SECRET123" not in message
    assert "SECRET456" not in message
    assert "SECRET789" not in message
    assert "[REDACTED]" in message
