"""Best-effort remote service health checks for the WebUI."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

import requests

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.health_check import check_and_select

ServiceStatus = Literal["checking", "ok", "warning", "error", "disabled"]
ServiceKind = Literal["llm", "data", "system"]

_REQUEST_TIMEOUT = 5
_MAX_ERROR_LEN = 300
_SECRET_KEYS = {"token", "apikey", "api_key"}


def _event(
    *,
    service_id: str,
    name: str,
    kind: ServiceKind,
    status: ServiceStatus,
    message: str,
    latency_ms: int | None = None,
) -> dict:
    return {
        "id": service_id,
        "name": name,
        "kind": kind,
        "status": status,
        "message": message[:_MAX_ERROR_LEN],
        "latency_ms": latency_ms,
    }


def _enabled_data_vendors(config: dict) -> set[str]:
    enabled: set[str] = set()
    data_vendors = config.get("data_vendors", {})
    tool_vendors = config.get("tool_vendors", {})
    for raw in [*data_vendors.values(), *tool_vendors.values()]:
        for vendor in str(raw).split(","):
            normalized = vendor.strip().lower()
            if normalized and normalized not in {"default", "disabled", "none", "off"}:
                enabled.add(normalized)
    return enabled


def _http_probe(
    url: str, *, params: dict | None = None, headers: dict | None = None
) -> tuple[bool, str, int]:
    start = time.monotonic()
    try:
        response = requests.get(url, params=params, headers=headers, timeout=_REQUEST_TIMEOUT)
        elapsed = int((time.monotonic() - start) * 1000)
        if 200 <= response.status_code < 400:
            return True, "Reachable", elapsed
        return False, f"HTTP {response.status_code}", elapsed
    except Exception as exc:  # noqa: BLE001 - any exception is a service failure
        elapsed = int((time.monotonic() - start) * 1000)
        message = _redact_secret_values(f"{type(exc).__name__}: {exc}", params)
        return False, message, elapsed


def _redact_secret_values(message: str, *containers: object) -> str:
    secrets: set[str] = set()

    def collect(value: object, key: str | None = None) -> None:
        if key and key.lower() in _SECRET_KEYS and value is not None:
            text = str(value)
            if text:
                secrets.add(text)
        elif isinstance(value, dict):
            for child_key, child_value in value.items():
                collect(child_value, str(child_key))
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    for container in containers:
        collect(container)

    redacted = message
    for secret in secrets:
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _json_probe(
    url: str,
    *,
    method: str = "GET",
    params: dict | None = None,
    json_payload: dict | None = None,
    headers: dict | None = None,
) -> tuple[bool, object, int]:
    start = time.monotonic()
    try:
        if method.upper() == "POST":
            response = requests.post(
                url,
                params=params,
                json=json_payload,
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
            )
        else:
            response = requests.get(url, params=params, headers=headers, timeout=_REQUEST_TIMEOUT)
        elapsed = int((time.monotonic() - start) * 1000)
        if not 200 <= response.status_code < 400:
            return False, f"HTTP {response.status_code}", elapsed
        return True, response.json(), elapsed
    except Exception as exc:  # noqa: BLE001 - any exception is a service failure
        elapsed = int((time.monotonic() - start) * 1000)
        message = _redact_secret_values(f"{type(exc).__name__}: {exc}", params, json_payload)
        return False, message, elapsed


def _today_compact() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")


def _format_compact_date(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def _normalize_date(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        if value > 10_000_000_000:
            value = value / 1000
        try:
            return datetime.fromtimestamp(value, tz=ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return None


def _extract_latest_date(payload: object) -> str | None:
    dates: list[str] = []

    def visit(value: object, key: str | None = None) -> None:
        if key and (
            key.lower()
            in {"date", "trade_date", "cal_date", "latesttradingday", "07. latest trading day"}
            or (isinstance(value, int) and key.lower() in {"timestamp", "time"})
        ):
            normalized = _normalize_date(value)
            if normalized:
                dates.append(normalized)

        if isinstance(value, dict):
            fields = value.get("fields")
            items = value.get("items")
            if isinstance(fields, list) and isinstance(items, list):
                date_indexes = [
                    index
                    for index, field in enumerate(fields)
                    if str(field).lower() in {"date", "trade_date", "cal_date"}
                ]
                for item in items:
                    if not isinstance(item, (list, tuple)):
                        continue
                    for index in date_indexes:
                        if index < len(item):
                            normalized = _normalize_date(item[index])
                            if normalized:
                                dates.append(normalized)

            for child_key, child_value in value.items():
                normalized_key = _normalize_date(child_key)
                if normalized_key:
                    dates.append(normalized_key)
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str) and "," in value:
            normalized = _normalize_date(value.split(",", 1)[0])
            if normalized:
                dates.append(normalized)

    visit(payload)
    return max(dates) if dates else None


def _freshness_status(latest_date: str) -> tuple[ServiceStatus, str]:
    expected = _today_compact()
    latest_label = _format_compact_date(latest_date)
    expected_label = _format_compact_date(expected)
    if latest_date == expected:
        return "ok", f"Reachable; latest daily data is {latest_label}"
    return (
        "warning",
        f"Reachable, but latest daily data is {latest_label}; expected {expected_label}",
    )


def _json_probe_args(probe_spec: dict, api_key: str | None) -> tuple[dict, dict]:
    params = dict(probe_spec.get("params", {}))
    json_payload = dict(probe_spec.get("json_payload", {}))

    key_target = probe_spec.get("api_key")
    if api_key and key_target == "params:apikey":
        params["apikey"] = api_key
    elif api_key and key_target == "params:api_key":
        params["api_key"] = api_key
    elif api_key and key_target == "json:token":
        json_payload["token"] = api_key

    return params, json_payload


def _run_json_reachability_probe(spec: dict, api_key: str | None) -> tuple[bool, str, int]:
    reachability = dict(spec["reachability"])
    params, json_payload = _json_probe_args(reachability, api_key)

    ok, payload, latency_ms = _json_probe(
        str(reachability["url"]),
        method=str(reachability.get("method", "GET")),
        params=params or None,
        json_payload=json_payload or None,
        headers=reachability.get("headers"),
    )
    if not ok:
        return False, str(payload), latency_ms
    return True, "Reachable", latency_ms


def _run_freshness_probe(spec: dict, api_key: str | None) -> tuple[ServiceStatus, str, int]:
    freshness = dict(spec["freshness"])
    params, json_payload = _json_probe_args(freshness, api_key)

    ok, payload, latency_ms = _json_probe(
        str(freshness["url"]),
        method=str(freshness.get("method", "GET")),
        params=params or None,
        json_payload=json_payload or None,
        headers=freshness.get("headers"),
    )
    if not ok:
        return "error", str(payload), latency_ms

    latest_date = _extract_latest_date(payload)
    if not latest_date:
        return "error", "Reachable, but freshness response had no usable date", latency_ms

    status, message = _freshness_status(latest_date)
    return status, message, latency_ms


def _probe_llm_services(config: dict) -> Iterator[dict]:
    yield _event(
        service_id="llm:provider",
        name=f"LLM Provider: {config.get('llm_provider', 'unknown')}",
        kind="llm",
        status="checking",
        message="Checking configured LLM models",
    )

    report = check_and_select(config)
    for slot, slot_report in report.slots.items():
        slot_label = "Deep LLM" if slot == "deep_think_llm" else "Quick LLM"
        for candidate in slot_report.candidates:
            selected = candidate.model == slot_report.selected
            if candidate.ok:
                message = "Reachable"
                if selected and slot_report.configured != slot_report.selected:
                    message = f"Reachable; selected fallback for {slot_label}"
                elif selected:
                    message = f"Reachable; selected for {slot_label}"
                status: ServiceStatus = "ok"
            else:
                message = candidate.error or "Unavailable"
                status = "error"
            yield _event(
                service_id=f"llm:{slot}:{candidate.model}",
                name=f"{slot_label}: {candidate.model}",
                kind="llm",
                status=status,
                message=message,
                latency_ms=candidate.latency_ms,
            )
    yield _event(
        service_id="llm:provider",
        name=f"LLM Provider: {report.provider}",
        kind="llm",
        status="error" if report.any_failed else "ok",
        message="One or more LLM slots have no reachable model"
        if report.any_failed
        else "Configured LLM provider has reachable models",
    )


_DATA_SERVICES = {
    "akshare": {
        "name": "AKShare",
        "url": "https://push2.eastmoney.com/api/qt/stock/get",
        "params": {"secid": "1.000001", "fields": "f43"},
        "env": None,
        "freshness": {
            "url": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            "params": {
                "secid": "1.000001",
                "klt": "101",
                "fqt": "1",
                "lmt": "1",
                "end": "20500101",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56",
            },
        },
    },
    "eastmoney": {
        # East Money direct-search news fallback (search-api-web), probed
        # separately from AKShare: this endpoint needs a browser UA + Referer,
        # and it can be up while the AKShare library layer is broken (or vice
        # versa). See eastmoney_news.get_news.
        "name": "Eastmoney 直连",
        "url": "https://search-api-web.eastmoney.com/search/jsonp",
        "params": {
            "cb": "x",
            "param": '{"uid":"","keyword":"510300","type":["cmsArticleWebOld"],'
            '"pageIndex":1,"pageSize":1}',
        },
        "headers": {"User-Agent": "Mozilla/5.0", "Referer": "https://so.eastmoney.com/"},
        "env": None,
    },
    "yfinance": {
        "name": "Yahoo Finance",
        "url": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
        "params": {"range": "1d", "interval": "1d"},
        "env": None,
        "freshness": {
            "url": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
            "params": {"range": "1d", "interval": "1d"},
        },
    },
    "alpha_vantage": {
        "name": "Alpha Vantage",
        "url": "https://www.alphavantage.co/query",
        "params": {"function": "GLOBAL_QUOTE", "symbol": "AAPL"},
        "env": "ALPHA_VANTAGE_API_KEY",
        "freshness": {
            "url": "https://www.alphavantage.co/query",
            "params": {"function": "GLOBAL_QUOTE", "symbol": "AAPL"},
            "api_key": "params:apikey",
        },
    },
    "tushare": {
        "name": "Tushare Pro",
        "url": "https://api.tushare.pro",
        "params": {
            "api_name": "trade_cal",
            "params": "{}",
            "fields": "cal_date,is_open",
        },
        "env": "TUSHARE_TOKEN",
        "reachability": {
            "url": "https://api.tushare.pro",
            "method": "POST",
            "json_payload": {
                "api_name": "trade_cal",
                "params": {},
                "fields": "cal_date,is_open",
            },
            "api_key": "json:token",
        },
        "freshness": {
            "url": "https://api.tushare.pro",
            "method": "POST",
            "json_payload": {
                "api_name": "daily",
                "params": {"ts_code": "000001.SZ", "limit": 1},
                "fields": "trade_date",
            },
            "api_key": "json:token",
        },
    },
    "fred": {
        "name": "FRED",
        "url": "https://api.stlouisfed.org/fred/series/observations",
        "params": {"series_id": "DGS10", "limit": "1", "file_type": "json"},
        "env": "FRED_API_KEY",
        "freshness": {
            "url": "https://api.stlouisfed.org/fred/series/observations",
            "params": {
                "series_id": "DGS10",
                "limit": "1",
                "file_type": "json",
                "sort_order": "desc",
            },
            "api_key": "params:api_key",
        },
    },
    "polymarket": {
        "name": "Polymarket",
        "url": "https://gamma-api.polymarket.com/markets",
        "params": {"limit": "1"},
        "env": None,
    },
}


def _probe_data_services(config: dict) -> Iterator[dict]:
    enabled = _enabled_data_vendors(config)
    for service_id, spec in _DATA_SERVICES.items():
        name = str(spec["name"])
        if service_id not in enabled:
            yield _event(
                service_id=f"data:{service_id}",
                name=name,
                kind="data",
                status="disabled",
                message="Disabled by current configuration",
            )
            continue

        env_var = spec.get("env")
        params = dict(spec["params"])
        api_key = None
        if env_var:
            api_key = os.getenv(str(env_var))
            if not api_key:
                yield _event(
                    service_id=f"data:{service_id}",
                    name=name,
                    kind="data",
                    status="error",
                    message=f"{env_var} is not set",
                )
                continue
            if service_id == "fred":
                params["api_key"] = api_key
            elif service_id == "tushare":
                pass
            else:
                params["apikey"] = api_key

        if "reachability" in spec:
            ok, message, latency_ms = _run_json_reachability_probe(spec, api_key)
        else:
            ok, message, latency_ms = _http_probe(
                str(spec["url"]), params=params, headers=spec.get("headers")
            )
        status: ServiceStatus = "ok" if ok else "error"
        if ok and "freshness" in spec:
            status, message, freshness_latency_ms = _run_freshness_probe(spec, api_key)
            latency_ms += freshness_latency_ms
        yield _event(
            service_id=f"data:{service_id}",
            name=name,
            kind="data",
            status=status,
            message=message,
            latency_ms=latency_ms,
        )


def generate_service_health_events(config: dict | None = None) -> Iterator[dict]:
    """Yield service status events followed by one summary event."""
    checks_config = dict(config or DEFAULT_CONFIG)
    statuses: dict[str, dict] = {}

    try:
        for status in _probe_llm_services(checks_config):
            statuses[status["id"]] = status
            yield {"event": "service_status", "data": status}
        for status in _probe_data_services(checks_config):
            statuses[status["id"]] = status
            yield {"event": "service_status", "data": status}
    except Exception as exc:  # noqa: BLE001 - health check must report, not crash
        status = _event(
            service_id="health:internal",
            name="Service health checker",
            kind="system",
            status="error",
            message=f"{type(exc).__name__}: {exc}",
        )
        statuses[status["id"]] = status
        yield {"event": "service_status", "data": status}

    latest = list(statuses.values())
    summary = {
        "total": len(latest),
        "checking": sum(1 for item in latest if item["status"] == "checking"),
        "ok": sum(1 for item in latest if item["status"] == "ok"),
        "warning": sum(1 for item in latest if item["status"] == "warning"),
        "error": sum(1 for item in latest if item["status"] == "error"),
        "disabled": sum(1 for item in latest if item["status"] == "disabled"),
    }
    yield {"event": "summary", "data": summary}


def probe_single_service_health(service_id: str, config: dict | None = None) -> dict | None:
    """Return a fresh status for exactly one service id, or None if unknown."""
    checks_config = dict(config or DEFAULT_CONFIG)

    if service_id.startswith("data:"):
        probes = _probe_data_services(checks_config)
    elif service_id.startswith("llm:"):
        probes = _probe_llm_services(checks_config)
    else:
        probes = iter(())

    for status in probes:
        if status["id"] == service_id:
            return status
    return None
