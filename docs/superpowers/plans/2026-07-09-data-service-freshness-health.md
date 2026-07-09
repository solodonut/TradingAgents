# Data Service Freshness Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend WebUI data service health checks so date-bearing vendors report `ok` for today's data, `warning` for stale-but-reachable data, and `error` for hard failures.

**Architecture:** Keep the existing `api/service_health.py` registry and routes, but add an optional freshness probe per data vendor. The backend remains the source of truth for status and summary counts; the frontend only learns a new `warning` status and displays it distinctly.

**Tech Stack:** Python 3.10+, FastAPI health routes, `requests`, pytest, Next.js 16, React 19, TypeScript, Node test runner.

---

## File Structure

- Modify `api/service_health.py`: add `warning` to backend status types, add JSON POST probing for Tushare, response-body date parsing helpers, per-service freshness probe metadata, and `warning` summary counts.
- Modify `tests/webui/test_routes_health.py`: add mocked backend tests for `warning`, Tushare, AKShare, Yahoo Finance, Alpha Vantage, FRED, and freshness short-circuit behavior.
- Modify `webui/lib/types.ts`: add `warning` to `ServiceHealthStatus` and `warning` to `ServiceHealthSummary`.
- Modify `webui/lib/service-health.ts`: place `warning` between `error` and `checking` in sort order.
- Modify `webui/lib/service-health.test.ts`: add a warning sort regression.
- Modify `webui/components/ServiceHealthPanel.tsx`: display warning label/icon/class, summary count, collapsed traffic light, and attention copy.

---

### Task 1: Backend Warning Summary Contract

**Files:**
- Modify: `api/service_health.py`
- Modify: `tests/webui/test_routes_health.py`

- [ ] **Step 1: Write failing backend summary test**

Append this test after `test_service_health_stream_emits_progress_and_summary` in `tests/webui/test_routes_health.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/webui/test_routes_health.py::test_service_health_stream_counts_warning_status -q
```

Expected: FAIL with `KeyError: 'warning'`.

- [ ] **Step 3: Add backend warning status and summary**

In `api/service_health.py`, change the status literal:

```python
ServiceStatus = Literal["checking", "ok", "warning", "error", "disabled"]
```

In `generate_service_health_events`, update the summary dict:

```python
    summary = {
        "total": len(latest),
        "checking": sum(1 for item in latest if item["status"] == "checking"),
        "ok": sum(1 for item in latest if item["status"] == "ok"),
        "warning": sum(1 for item in latest if item["status"] == "warning"),
        "error": sum(1 for item in latest if item["status"] == "error"),
        "disabled": sum(1 for item in latest if item["status"] == "disabled"),
    }
```

- [ ] **Step 4: Run focused backend summary test**

Run:

```bash
pytest tests/webui/test_routes_health.py::test_service_health_stream_counts_warning_status -q
```

Expected: PASS.

- [ ] **Step 5: Commit backend warning summary**

```bash
git add api/service_health.py tests/webui/test_routes_health.py
git commit -m "feat(webui): add warning service health status"
```

---

### Task 2: Backend Freshness Probe Helpers

**Files:**
- Modify: `api/service_health.py`
- Modify: `tests/webui/test_routes_health.py`

- [ ] **Step 1: Write helper unit tests**

Append these tests near the other data probe tests in `tests/webui/test_routes_health.py`:

```python
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
```

- [ ] **Step 2: Run helper tests to verify they fail**

Run:

```bash
pytest \
  tests/webui/test_routes_health.py::test_freshness_status_reports_ok_for_today \
  tests/webui/test_routes_health.py::test_freshness_status_reports_warning_for_stale_date \
  tests/webui/test_routes_health.py::test_extract_latest_date_handles_nested_vendor_payloads \
  -q
```

Expected: FAIL because `_freshness_status`, `_today_compact`, and `_extract_latest_date` do not exist.

- [ ] **Step 3: Implement date parsing helpers**

Add these imports to `api/service_health.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo
```

Add these helpers after `_http_probe`:

```python
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
        if key and key.lower() in {"date", "trade_date", "cal_date", "latesttradingday"}:
            normalized = _normalize_date(value)
            if normalized:
                dates.append(normalized)
        elif isinstance(value, int) and key and key.lower() in {"timestamp", "time"}:
            normalized = _normalize_date(value)
            if normalized:
                dates.append(normalized)

        if isinstance(value, dict):
            for child_key, child_value in value.items():
                normalized_key = _normalize_date(child_key)
                if normalized_key:
                    dates.append(normalized_key)
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child)

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
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
pytest \
  tests/webui/test_routes_health.py::test_freshness_status_reports_ok_for_today \
  tests/webui/test_routes_health.py::test_freshness_status_reports_warning_for_stale_date \
  tests/webui/test_routes_health.py::test_extract_latest_date_handles_nested_vendor_payloads \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit freshness helpers**

```bash
git add api/service_health.py tests/webui/test_routes_health.py
git commit -m "feat(health): add data freshness date helpers"
```

---

### Task 3: Backend Vendor Freshness Probes

**Files:**
- Modify: `api/service_health.py`
- Modify: `tests/webui/test_routes_health.py`

- [ ] **Step 1: Write vendor freshness tests**

Replace the existing `test_data_probe_reports_tushare_reachable` with these tests:

```python
def test_data_probe_reports_tushare_fresh_today(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    monkeypatch.setattr("api.service_health._today_compact", lambda: "20260709")
    monkeypatch.setattr(
        "api.service_health._http_probe",
        lambda url, params=None, headers=None: (True, "Reachable", 12),
    )
    monkeypatch.setattr(
        "api.service_health._json_probe",
        lambda url, method="GET", params=None, json_payload=None, headers=None: (
            True,
            {"data": {"items": [{"trade_date": "20260709"}]}},
            24,
        ),
    )

    statuses = list(_probe_data_services({"data_vendors": {"core_stock_apis": "tushare"}}))

    tushare = next(item for item in statuses if item["id"] == "data:tushare")
    assert tushare["status"] == "ok"
    assert tushare["latency_ms"] == 36
    assert "latest daily data is 2026-07-09" in tushare["message"]


def test_data_probe_reports_tushare_warning_when_stale(monkeypatch):
    from api.service_health import _probe_data_services

    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    monkeypatch.setattr("api.service_health._today_compact", lambda: "20260709")
    monkeypatch.setattr(
        "api.service_health._http_probe",
        lambda url, params=None, headers=None: (True, "Reachable", 12),
    )
    monkeypatch.setattr(
        "api.service_health._json_probe",
        lambda url, method="GET", params=None, json_payload=None, headers=None: (
            True,
            {"data": {"items": [{"trade_date": "20260708"}]}},
            24,
        ),
    )

    statuses = list(_probe_data_services({"data_vendors": {"core_stock_apis": "tushare"}}))

    tushare = next(item for item in statuses if item["id"] == "data:tushare")
    assert tushare["status"] == "warning"
    assert "latest daily data is 2026-07-08; expected 2026-07-09" in tushare["message"]


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
    monkeypatch.setattr(
        "api.service_health._http_probe",
        lambda url, params=None, headers=None: (True, "Reachable", 11),
    )
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
```

- [ ] **Step 2: Run vendor tests to verify they fail**

Run:

```bash
pytest tests/webui/test_routes_health.py -q
```

Expected: FAIL because `_json_probe` and freshness wiring do not exist, and the old Tushare reachable expectations no longer match.

- [ ] **Step 3: Implement JSON probe and per-vendor freshness specs**

Add this helper after `_http_probe` in `api/service_health.py`:

```python
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
        if method == "POST":
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
        return False, f"{type(exc).__name__}: {exc}", elapsed
```

Update `_extract_latest_date` so AKShare kline strings also parse:

```python
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str) and "," in value:
            normalized = _normalize_date(value.split(",", 1)[0])
            if normalized:
                dates.append(normalized)
```

Add freshness metadata to `_DATA_SERVICES` entries:

```python
    "akshare": {
        "name": "AKShare",
        "url": "https://push2.eastmoney.com/api/qt/stock/get",
        "params": {"secid": "1.000001", "fields": "f43"},
        "freshness": {
            "url": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            "params": {
                "secid": "1.000001",
                "klt": "101",
                "fqt": "1",
                "lmt": "1",
                "end": "20500101",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57",
            },
        },
        "env": None,
    },
```

```python
    "yfinance": {
        "name": "Yahoo Finance",
        "url": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
        "params": {"range": "1d", "interval": "1d"},
        "freshness": {
            "url": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
            "params": {"range": "1d", "interval": "1d"},
        },
        "env": None,
    },
```

```python
    "alpha_vantage": {
        "name": "Alpha Vantage",
        "url": "https://www.alphavantage.co/query",
        "params": {"function": "GLOBAL_QUOTE", "symbol": "AAPL"},
        "freshness": {
            "url": "https://www.alphavantage.co/query",
            "params": {"function": "GLOBAL_QUOTE", "symbol": "AAPL"},
        },
        "env": "ALPHA_VANTAGE_API_KEY",
    },
```

```python
    "tushare": {
        "name": "Tushare Pro",
        "url": "https://api.tushare.pro",
        "params": {
            "api_name": "trade_cal",
            "params": "{}",
            "fields": "cal_date,is_open",
        },
        "freshness": {
            "url": "https://api.tushare.pro",
            "method": "POST",
            "json": {
                "api_name": "daily",
                "params": {"ts_code": "000001.SZ", "start_date": "19900101", "end_date": "20500101"},
                "fields": "trade_date,close",
            },
            "token_in_json": True,
        },
        "env": "TUSHARE_TOKEN",
    },
```

```python
    "fred": {
        "name": "FRED",
        "url": "https://api.stlouisfed.org/fred/series/observations",
        "params": {"series_id": "DGS10", "limit": "1", "file_type": "json"},
        "freshness": {
            "url": "https://api.stlouisfed.org/fred/series/observations",
            "params": {"series_id": "DGS10", "limit": "1", "sort_order": "desc", "file_type": "json"},
        },
        "env": "FRED_API_KEY",
    },
```

Then add this helper after `_freshness_status`:

```python
def _run_freshness_probe(spec: dict, api_key: str | None) -> tuple[ServiceStatus, str, int]:
    freshness = spec.get("freshness")
    if not isinstance(freshness, dict):
        return "ok", "Reachable", 0

    params = dict(freshness.get("params") or {})
    json_payload = freshness.get("json")
    if isinstance(json_payload, dict):
        json_payload = dict(json_payload)

    env_var = spec.get("env")
    if api_key and env_var:
        if freshness.get("token_in_json") and isinstance(json_payload, dict):
            json_payload["token"] = api_key
        elif env_var == "FRED_API_KEY":
            params["api_key"] = api_key
        elif env_var == "ALPHA_VANTAGE_API_KEY":
            params["apikey"] = api_key

    ok, payload, latency_ms = _json_probe(
        str(freshness["url"]),
        method=str(freshness.get("method", "GET")),
        params=params,
        json_payload=json_payload,
        headers=freshness.get("headers"),
    )
    if not ok:
        return "error", str(payload), latency_ms

    latest_date = _extract_latest_date(payload)
    if not latest_date:
        return "error", "Reachable, but freshness response had no usable date", latency_ms
    status, message = _freshness_status(latest_date)
    return status, message, latency_ms
```

Update `_probe_data_services` so it passes the API key into both reachability and freshness paths:

```python
        api_key = None
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
            if service_id == "fred":
                params["api_key"] = api_key
            elif service_id == "tushare":
                params["token"] = api_key
            else:
                params["apikey"] = api_key

        ok, message, latency_ms = _http_probe(
            str(spec["url"]), params=params, headers=spec.get("headers")
        )
        status: ServiceStatus = "ok" if ok else "error"
        if ok and spec.get("freshness"):
            status, message, freshness_latency = _run_freshness_probe(spec, api_key)
            latency_ms += freshness_latency
        yield _event(
            service_id=f"data:{service_id}",
            name=name,
            kind="data",
            status=status,
            message=message,
            latency_ms=latency_ms,
        )
```

- [ ] **Step 4: Run backend health tests**

Run:

```bash
pytest tests/webui/test_routes_health.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit vendor freshness probes**

```bash
git add api/service_health.py tests/webui/test_routes_health.py
git commit -m "feat(health): verify data service freshness"
```

---

### Task 4: Frontend Warning Types and Sorting

**Files:**
- Modify: `webui/lib/types.ts`
- Modify: `webui/lib/service-health.ts`
- Modify: `webui/lib/service-health.test.ts`

- [ ] **Step 1: Write failing sort test**

Update `webui/lib/service-health.test.ts` by adding warning to the first test:

```ts
test("sortServiceHealthItems orders reachable, errors, warnings, checking, then disabled", () => {
  const sorted = sortServiceHealthItems([
    item("disabled-a", "disabled"),
    item("warning-a", "warning"),
    item("error-a", "error"),
    item("ok-a", "ok"),
    item("checking-a", "checking"),
    item("error-b", "error"),
    item("disabled-b", "disabled"),
    item("ok-b", "ok"),
  ]);

  assert.deepEqual(
    sorted.map((service) => service.id),
    [
      "ok-a",
      "ok-b",
      "error-a",
      "error-b",
      "warning-a",
      "checking-a",
      "disabled-a",
      "disabled-b",
    ],
  );
});
```

Keep the second existing checking test.

- [ ] **Step 2: Run frontend test to verify it fails**

Run:

```bash
cd webui && npm test -- service-health
```

Expected: FAIL with TypeScript/type or sort-order failure because `warning` is not a valid status.

- [ ] **Step 3: Add warning to frontend types and sort order**

In `webui/lib/types.ts`, update:

```ts
export type ServiceHealthStatus = "checking" | "ok" | "warning" | "error" | "disabled";
```

In `ServiceHealthSummary`, add:

```ts
  warning: number;
```

In `webui/lib/service-health.ts`, update:

```ts
const STATUS_ORDER: Record<ServiceHealthItem["status"], number> = {
  ok: 0,
  error: 1,
  warning: 2,
  checking: 3,
  disabled: 4,
};
```

- [ ] **Step 4: Run frontend service-health tests**

Run:

```bash
cd webui && npm test -- service-health
```

Expected: PASS.

- [ ] **Step 5: Commit frontend warning types**

```bash
git add webui/lib/types.ts webui/lib/service-health.ts webui/lib/service-health.test.ts
git commit -m "feat(webui): sort warning service health"
```

---

### Task 5: Frontend Warning Panel Display

**Files:**
- Modify: `webui/components/ServiceHealthPanel.tsx`

- [ ] **Step 1: Update warning UI helpers**

In `webui/components/ServiceHealthPanel.tsx`, add `CircleAlert` to the lucide imports:

```ts
  CircleAlert,
```

Update `statusLabel`:

```ts
function statusLabel(status: ServiceHealthItem["status"]): string {
  if (status === "ok") return "可达";
  if (status === "warning") return "警告";
  if (status === "error") return "异常";
  if (status === "disabled") return "禁用";
  return "检查中";
}
```

Update `statusClass`:

```ts
function statusClass(status: ServiceHealthItem["status"]): string {
  if (status === "ok") return "text-emerald-300";
  if (status === "warning") return "text-amber-300";
  if (status === "error") return "text-destructive";
  if (status === "disabled") return "text-muted-foreground";
  return "text-amber-300";
}
```

Update `StatusIcon`:

```tsx
function StatusIcon({ status }: { status: ServiceHealthItem["status"] }) {
  if (status === "ok") return <CheckCircle2 className="size-3.5" aria-hidden="true" />;
  if (status === "warning") return <CircleAlert className="size-3.5" aria-hidden="true" />;
  if (status === "error") return <AlertTriangle className="size-3.5" aria-hidden="true" />;
  if (status === "disabled") return <Ban className="size-3.5" aria-hidden="true" />;
  return (
    <LoaderCircle
      className="size-3.5 animate-spin motion-reduce:animate-none"
      aria-hidden="true"
    />
  );
}
```

- [ ] **Step 2: Update traffic light and summary display**

In `trafficLight`, add warning handling between error and checking:

```ts
  if (items.some((item) => item.status === "warning")) {
    return {
      className: "bg-amber-300 shadow-[0_0_14px_rgba(252,211,77,0.55)]",
      label: "警告",
    };
  }
```

Inside the component, add:

```ts
  const hasWarnings = items.some((item) => item.status === "warning");
```

Update the summary line:

```tsx
                OK {summary.ok} · Warning {summary.warning} · Error {summary.error} · Disabled{" "}
                {summary.disabled}
```

Update the collapsed attention copy:

```tsx
          {hasFailures && !expanded && (
            <span className="hidden font-mono text-[0.65rem] uppercase tracking-[0.12em] text-destructive sm:inline">
              有服务不可达
            </span>
          )}
          {!hasFailures && hasWarnings && !expanded && (
            <span className="hidden font-mono text-[0.65rem] uppercase tracking-[0.12em] text-amber-300 sm:inline">
              有数据未更新
            </span>
          )}
```

Keep `hasFailures` tied only to `error` so warnings do not get red border styling.

- [ ] **Step 3: Run frontend checks**

Run:

```bash
cd webui && npm test -- service-health
npm run lint
```

Expected: tests PASS and lint exits 0.

- [ ] **Step 4: Commit warning panel display**

```bash
git add webui/components/ServiceHealthPanel.tsx
git commit -m "feat(webui): display warning health state"
```

---

### Task 6: Final Verification

**Files:**
- Verify only; no planned edits.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
pytest tests/webui/test_routes_health.py -q
```

Expected: PASS.

- [ ] **Step 2: Run focused frontend tests**

Run:

```bash
cd webui && npm test -- service-health
```

Expected: PASS.

- [ ] **Step 3: Run lint**

Run from repo root:

```bash
ruff check api/service_health.py tests/webui/test_routes_health.py
```

Expected: PASS.

Run from `webui/`:

```bash
npm run lint
```

Expected: PASS.

- [ ] **Step 4: Inspect final diff**

Run:

```bash
git diff --stat HEAD~4..HEAD
git status --short
```

Expected: diff shows only health-check related files from this plan. Existing unrelated ETF working-tree files may still appear in `git status --short`; do not stage or revert them.

- [ ] **Step 5: Commit any verification fixes**

If verification required small fixes, commit only those files:

```bash
git add api/service_health.py tests/webui/test_routes_health.py webui/lib/types.ts webui/lib/service-health.ts webui/lib/service-health.test.ts webui/components/ServiceHealthPanel.tsx
git commit -m "fix(health): polish freshness warning checks"
```

If no fixes were needed, do not create an empty commit.

---

## Self-Review

- Spec coverage: backend `warning`, freshness checks for Tushare, AKShare, Yahoo Finance, Alpha Vantage, and FRED, reachability short-circuiting, summary counts, and frontend warning display are all mapped to tasks.
- Scope check: Eastmoney and Polymarket remain reachability-only as specified.
- Placeholder scan: every implementation step includes concrete code or commands; no deferred work markers remain.
- Type consistency: backend uses `warning` in `ServiceStatus`; frontend uses `warning` in `ServiceHealthStatus` and `ServiceHealthSummary`; tests use the same strings.
