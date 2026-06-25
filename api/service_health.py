"""Best-effort remote service health checks for the WebUI."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from typing import Literal

import requests

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.health_check import check_and_select

ServiceStatus = Literal["checking", "ok", "error", "disabled"]
ServiceKind = Literal["llm", "data", "system"]

_REQUEST_TIMEOUT = 5
_MAX_ERROR_LEN = 300


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


def _http_probe(url: str, *, params: dict | None = None) -> tuple[bool, str, int]:
    start = time.monotonic()
    try:
        response = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        elapsed = int((time.monotonic() - start) * 1000)
        if 200 <= response.status_code < 400:
            return True, "Reachable", elapsed
        return False, f"HTTP {response.status_code}", elapsed
    except Exception as exc:  # noqa: BLE001 - any exception is a service failure
        elapsed = int((time.monotonic() - start) * 1000)
        return False, f"{type(exc).__name__}: {exc}", elapsed


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
        "name": "AKShare / Eastmoney",
        "url": "https://push2.eastmoney.com/api/qt/stock/get",
        "params": {"secid": "1.000001", "fields": "f43"},
        "env": None,
    },
    "yfinance": {
        "name": "Yahoo Finance",
        "url": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
        "params": {"range": "1d", "interval": "1d"},
        "env": None,
    },
    "alpha_vantage": {
        "name": "Alpha Vantage",
        "url": "https://www.alphavantage.co/query",
        "params": {"function": "GLOBAL_QUOTE", "symbol": "AAPL"},
        "env": "ALPHA_VANTAGE_API_KEY",
    },
    "fred": {
        "name": "FRED",
        "url": "https://api.stlouisfed.org/fred/series/observations",
        "params": {"series_id": "DGS10", "limit": "1", "file_type": "json"},
        "env": "FRED_API_KEY",
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
            params["apikey" if service_id != "fred" else "api_key"] = api_key

        ok, message, latency_ms = _http_probe(str(spec["url"]), params=params)
        yield _event(
            service_id=f"data:{service_id}",
            name=name,
            kind="data",
            status="ok" if ok else "error",
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
        "error": sum(1 for item in latest if item["status"] == "error"),
        "disabled": sum(1 for item in latest if item["status"] == "disabled"),
    }
    yield {"event": "summary", "data": summary}
