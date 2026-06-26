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


def test_data_probe_marks_unconfigured_services_disabled(monkeypatch):
    import api.service_health as service_health

    monkeypatch.setattr(service_health, "_http_probe", lambda url, params=None: (True, "ok", 1))

    statuses = list(
        service_health._probe_data_services({"data_vendors": {"core_stock_apis": "akshare"}})
    )

    by_id = {item["id"]: item for item in statuses}
    assert by_id["data:yfinance"]["status"] == "disabled"
    assert by_id["data:fred"]["status"] == "disabled"
    assert by_id["data:polymarket"]["status"] == "disabled"


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


def test_data_probe_reports_tushare_reachable(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    monkeypatch.setattr(
        "api.service_health._http_probe",
        lambda url, params=None: (True, "Reachable", 12),
    )

    statuses = list(
        _probe_data_services({"data_vendors": {"core_stock_apis": "tushare,akshare"}})
    )

    tushare = next(item for item in statuses if item["id"] == "data:tushare")
    assert tushare["status"] == "ok"
    assert tushare["latency_ms"] == 12
