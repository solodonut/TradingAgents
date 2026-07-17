import json


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
            "id": "data:akshare",
            "name": "AKShare / Eastmoney",
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
            "id": "data:akshare",
            "name": "AKShare",
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
            "id": "data:akshare",
            "name": "AKShare / Eastmoney",
            "kind": "data",
            "status": "error",
            "message": "HTTP 503",
            "latency_ms": 55,
        }

    monkeypatch.setattr(service_health, "_probe_llm_services", fake_llm_probe)
    monkeypatch.setattr(service_health, "_probe_data_services", fake_data_probe)

    response = client.get("/api/health/services/data:akshare")

    assert response.status_code == 200
    assert response.json() == {
        "id": "data:akshare",
        "name": "AKShare / Eastmoney",
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
        service_health._probe_data_services({"data_vendors": {"core_stock_apis": "akshare"}})
    )

    by_id = {item["id"]: item for item in statuses}
    assert by_id["data:yfinance"]["status"] == "disabled"
    assert by_id["data:fred"]["status"] == "disabled"
    assert by_id["data:polymarket"]["status"] == "disabled"


def test_data_probe_splits_akshare_and_eastmoney(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setattr("api.service_health._today_compact", lambda: "20260709")
    monkeypatch.setattr(
        "api.service_health._http_probe",
        lambda url, params=None, headers=None: (True, "Reachable", 9),
    )
    monkeypatch.setattr(
        "api.service_health._json_probe",
        lambda url, method="GET", params=None, json_payload=None, headers=None: (
            True,
            {"data": {"klines": ["2026-07-09,10,11,12,9,100"]}},
            13,
        ),
    )

    statuses = list(
        _probe_data_services({"tool_vendors": {"get_news": "akshare,eastmoney,longbridge"}})
    )

    by_id = {item["id"]: item for item in statuses}
    # AKShare (library backend) and Eastmoney (direct search) are probed as two
    # separate rows so a library-level break is distinguishable from a source outage.
    assert by_id["data:akshare"]["name"] == "AKShare"
    assert by_id["data:akshare"]["status"] == "ok"
    assert by_id["data:eastmoney"]["name"] == "Eastmoney 直连"
    assert by_id["data:eastmoney"]["status"] == "ok"


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
        _probe_data_services({"data_vendors": {"core_stock_apis": "tushare,akshare"}})
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
    monkeypatch.setattr(
        "api.service_health._http_probe",
        lambda url, params=None, headers=None: (False, "HTTP 503", 12),
    )

    def json_probe(*args, **kwargs):
        calls["freshness"] += 1
        return True, {"data": {"items": [{"trade_date": "20260709"}]}}, 24

    monkeypatch.setattr("api.service_health._json_probe", json_probe)

    statuses = list(_probe_data_services({"data_vendors": {"core_stock_apis": "akshare"}}))

    akshare = next(item for item in statuses if item["id"] == "data:akshare")
    assert akshare["status"] == "error"
    assert akshare["message"] == "HTTP 503"
    assert calls["freshness"] == 0


def test_data_probe_reports_akshare_warning_when_stale(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setattr("api.service_health._today_compact", lambda: "20260709")
    monkeypatch.setattr(
        "api.service_health._http_probe",
        lambda url, params=None, headers=None: (True, "Reachable", 9),
    )
    monkeypatch.setattr(
        "api.service_health._json_probe",
        lambda url, method="GET", params=None, json_payload=None, headers=None: (
            True,
            {"data": {"klines": ["2026-07-08,10,11,12,9,100"]}},
            13,
        ),
    )

    statuses = list(_probe_data_services({"data_vendors": {"core_stock_apis": "akshare"}}))

    akshare = next(item for item in statuses if item["id"] == "data:akshare")
    assert akshare["status"] == "warning"
    assert "latest daily data is 2026-07-08; expected 2026-07-09" in akshare["message"]


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

    statuses = list(_probe_data_services({"data_vendors": {"core_stock_apis": "akshare"}}))

    akshare = next(item for item in statuses if item["id"] == "data:akshare")
    assert akshare["status"] == "error"
    assert akshare["message"] == "Reachable, but freshness response had no usable date"


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
        _probe_data_services({"data_vendors": {"core_stock_apis": "akshare"}})
    )

    ad = next(item for item in statuses if item["id"] == "data:amazingdata")
    assert ad["status"] == "disabled"


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
