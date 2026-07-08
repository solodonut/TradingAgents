# Startup Cache Clear Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear endpoint local data caches on every WebUI API startup, show progress in the UI, and block analysis until clearing succeeds.

**Architecture:** Add a backend `StartupCacheClearer` service with process-local progress state, expose status/SSE routes, and make analysis/queue scheduling consult a single startup gate. The frontend fetches/subscribes to the startup cache state, renders it as a `system` item in the existing Service Health panel, and disables analysis controls until the backend reports `completed`.

**Tech Stack:** FastAPI, sse-starlette, pytest, Next.js 16, React 19, TypeScript, Node test runner.

---

## File Structure

- Create `api/startup_cache.py`: cache-clearing service, dataclasses, cache-root scanning, SSE event generator, and route guard helper.
- Create `api/routes/startup_cache.py`: `GET /api/startup-cache/status` and `GET /api/startup-cache/stream`.
- Modify `api/main.py`: initialize `app.state.startup_cache_clearer`, include router, start the clear task at startup, and advance scheduler only after success.
- Modify `api/scheduler.py`: return early while startup cache is not ready.
- Modify `api/routes/analysis.py`: block `POST /api/analysis` while startup cache is not ready.
- Modify `api/routes/queue.py`: block `POST /api/queue` while startup cache is not ready.
- Create `tests/webui/test_startup_cache.py`: unit/API tests for deletion, checkpoint exclusion, errors, status, SSE, and gate behavior.
- Modify `tests/webui/conftest.py`: reset startup cache app state between tests.
- Modify `webui/lib/types.ts`: startup cache status/event types.
- Modify `webui/lib/api.ts`: startup cache status and SSE helpers.
- Create `webui/lib/startup-cache.ts`: conversion/format helpers for Service Health display.
- Create `webui/lib/startup-cache.test.ts`: helper tests.
- Modify `webui/components/ServiceHealthPanel.tsx`: accept and render optional startup maintenance item details.
- Modify `webui/components/ConfigCard.tsx`: accept disabled reason for startup gate.
- Modify `webui/components/QueuePanel.tsx`: disable queue mutating controls during startup gate.
- Modify `webui/app/page.tsx`: load/subscribe startup cache state and wire disabled controls.

---

### Task 1: Backend Startup Cache Clearer

**Files:**
- Create: `api/startup_cache.py`
- Test: `tests/webui/test_startup_cache.py`

- [ ] **Step 1: Write failing tests for deletion, checkpoint exclusion, and error state**

Add this new file:

```python
from pathlib import Path


def test_startup_cache_clearer_deletes_endpoint_cache_files(tmp_path):
    from api.startup_cache import StartupCacheClearer

    cache_root = tmp_path / "cache"
    ak_file = cache_root / "akshare" / "hist_600519.pkl"
    csv_file = cache_root / "NVDA-YFin-data-2020-01-01-2025-01-01.csv"
    checkpoint_file = cache_root / "checkpoints" / "NVDA.db"
    ak_file.parent.mkdir(parents=True)
    checkpoint_file.parent.mkdir(parents=True)
    ak_file.write_bytes(b"ak-cache")
    csv_file.write_text("Date,Close\n2026-07-08,1\n", encoding="utf-8")
    checkpoint_file.write_bytes(b"checkpoint")

    clearer = StartupCacheClearer(cache_root=cache_root)
    clearer.run_sync()

    state = clearer.snapshot()
    assert state["status"] == "completed"
    assert state["deleted_files"] == 2
    assert state["released_bytes"] >= len(b"ak-cache")
    assert not ak_file.exists()
    assert not csv_file.exists()
    assert checkpoint_file.exists()


def test_startup_cache_clearer_error_blocks_on_delete_failure(tmp_path, monkeypatch):
    from api.startup_cache import StartupCacheClearer

    cache_root = tmp_path / "cache"
    doomed = cache_root / "akshare" / "bad.pkl"
    doomed.parent.mkdir(parents=True)
    doomed.write_bytes(b"bad")

    original_unlink = Path.unlink

    def fail_for_bad(self):
        if self == doomed:
            raise PermissionError("locked")
        return original_unlink(self)

    monkeypatch.setattr(Path, "unlink", fail_for_bad)

    clearer = StartupCacheClearer(cache_root=cache_root)
    clearer.run_sync()

    state = clearer.snapshot()
    assert state["status"] == "error"
    assert state["errors"] == [{"path": "akshare/bad.pkl", "message": "locked"}]
    assert doomed.exists()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
pytest tests/webui/test_startup_cache.py::test_startup_cache_clearer_deletes_endpoint_cache_files tests/webui/test_startup_cache.py::test_startup_cache_clearer_error_blocks_on_delete_failure -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'api.startup_cache'`.

- [ ] **Step 3: Implement `api/startup_cache.py`**

Create:

```python
"""Startup endpoint cache clearing and progress reporting."""

from __future__ import annotations

import json
import queue
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

from fastapi import HTTPException, Request

StartupCacheStatus = Literal["pending", "running", "completed", "error"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StartupCacheError:
    path: str
    message: str


@dataclass
class StartupCacheState:
    status: StartupCacheStatus = "pending"
    phase: str = "pending"
    message: str = "等待启动缓存清理"
    current_path: str | None = None
    processed_items: int = 0
    total_items: int = 0
    deleted_files: int = 0
    released_bytes: int = 0
    errors: list[StartupCacheError] = field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str | None = None


class StartupCacheClearer:
    """Clear endpoint data caches once per API process startup."""

    def __init__(self, cache_root: str | Path, *, max_errors: int = 20):
        self.cache_root = Path(cache_root).expanduser()
        self.max_errors = max_errors
        self._state = StartupCacheState()
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue[dict | None]] = []
        self._thread: threading.Thread | None = None
        self._on_complete = None

    def start(self, *, on_complete=None) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._on_complete = on_complete
            self._thread = threading.Thread(target=self._run_and_callback, daemon=True)
            self._thread.start()

    def run_sync(self) -> None:
        self._run()

    def snapshot(self) -> dict:
        with self._lock:
            return self._state_dict_locked()

    def is_ready(self) -> bool:
        return self.snapshot()["status"] == "completed"

    def subscribe(self) -> Iterator[dict]:
        q: queue.Queue[dict | None] = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
            q.put({"event": "cache_clear_status", "data": self._state_dict_locked()})

        try:
            while True:
                item = q.get()
                if item is None:
                    break
                yield item
                data = item["data"]
                if data.get("status") in {"completed", "error"}:
                    yield {"event": "summary", "data": data}
                    break
        finally:
            with self._lock:
                if q in self._subscribers:
                    self._subscribers.remove(q)

    def _run_and_callback(self) -> None:
        self._run()
        if self._on_complete is not None:
            self._on_complete(self.snapshot())

    def _run(self) -> None:
        self._update(
            status="running",
            phase="scanning",
            message="正在扫描 endpoint 本地数据缓存",
            started_at=_now_iso(),
            updated_at=_now_iso(),
        )
        targets = self._scan_targets()
        self._update(
            total_items=len(targets),
            phase="deleting",
            message="正在清理 endpoint 本地数据缓存",
            updated_at=_now_iso(),
        )

        for path in targets:
            rel = self._relative(path)
            size = path.stat().st_size if path.exists() and path.is_file() else 0
            self._update(current_path=rel, updated_at=_now_iso())
            try:
                path.unlink()
                self._increment_success(size)
            except Exception as exc:  # noqa: BLE001 - report and continue
                self._record_error(rel, str(exc))

        final_status: StartupCacheStatus = "error" if self.snapshot()["errors"] else "completed"
        final_message = (
            "启动缓存清理失败，暂不能开始分析"
            if final_status == "error"
            else "启动缓存清理完成"
        )
        self._update(
            status=final_status,
            phase=final_status,
            message=final_message,
            current_path=None,
            completed_at=_now_iso(),
            updated_at=_now_iso(),
        )
        self._close_subscribers()

    def _scan_targets(self) -> list[Path]:
        if not self.cache_root.exists():
            return []

        targets: list[Path] = []
        for path in self.cache_root.rglob("*"):
            if not path.is_file():
                continue
            if self._is_excluded(path):
                continue
            targets.append(path)
        return sorted(targets)

    def _is_excluded(self, path: Path) -> bool:
        try:
            rel = path.relative_to(self.cache_root)
        except ValueError:
            return True
        return rel.parts[:1] == ("checkpoints",)

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.cache_root).as_posix()
        except ValueError:
            return path.name

    def _increment_success(self, size: int) -> None:
        with self._lock:
            self._state.processed_items += 1
            self._state.deleted_files += 1
            self._state.released_bytes += size
            self._state.updated_at = _now_iso()
            data = self._state_dict_locked()
        self._publish(data)

    def _record_error(self, rel: str, message: str) -> None:
        with self._lock:
            self._state.processed_items += 1
            if len(self._state.errors) < self.max_errors:
                self._state.errors.append(StartupCacheError(path=rel, message=message))
            self._state.updated_at = _now_iso()
            data = self._state_dict_locked()
        self._publish(data)

    def _update(self, **changes) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(self._state, key, value)
            data = self._state_dict_locked()
        self._publish(data)

    def _state_dict_locked(self) -> dict:
        data = asdict(self._state)
        data["cache_root"] = str(self.cache_root)
        return data

    def _publish(self, data: dict) -> None:
        item = {"event": "cache_clear_status", "data": data}
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(item)

    def _close_subscribers(self) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(None)


def get_startup_cache_clearer(request: Request) -> StartupCacheClearer | None:
    return getattr(request.app.state, "startup_cache_clearer", None)


def assert_startup_cache_ready(request: Request) -> None:
    clearer = get_startup_cache_clearer(request)
    if clearer is None:
        return
    if not clearer.is_ready():
        raise HTTPException(status_code=503, detail="启动缓存清理未完成，暂不能开始分析")


def sse_json(item: dict) -> dict:
    return {"event": item["event"], "data": json.dumps(item["data"])}
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
pytest tests/webui/test_startup_cache.py::test_startup_cache_clearer_deletes_endpoint_cache_files tests/webui/test_startup_cache.py::test_startup_cache_clearer_error_blocks_on_delete_failure -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/startup_cache.py tests/webui/test_startup_cache.py
git commit -m "feat(api): add startup cache clearer"
```

---

### Task 2: Startup Cache API Routes

**Files:**
- Create: `api/routes/startup_cache.py`
- Modify: `api/main.py`
- Modify: `tests/webui/conftest.py`
- Test: `tests/webui/test_startup_cache.py`

- [ ] **Step 1: Add failing route tests**

Append to `tests/webui/test_startup_cache.py`:

```python
def test_startup_cache_status_route(client, tmp_path):
    import api.main as main
    from api.startup_cache import StartupCacheClearer

    clearer = StartupCacheClearer(tmp_path / "cache")
    clearer.run_sync()
    main.app.state.startup_cache_clearer = clearer

    resp = client.get("/api/startup-cache/status")

    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_startup_cache_stream_route(client, tmp_path):
    import api.main as main
    from api.startup_cache import StartupCacheClearer

    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    (cache_root / "one.csv").write_text("x", encoding="utf-8")
    clearer = StartupCacheClearer(cache_root)
    clearer.run_sync()
    main.app.state.startup_cache_clearer = clearer

    with client.stream("GET", "/api/startup-cache/stream") as stream:
        body = "".join(stream.iter_text())

    assert "event: cache_clear_status" in body
    assert "event: summary" in body
    assert '"status": "completed"' in body
```

- [ ] **Step 2: Run route tests and verify they fail**

Run:

```bash
pytest tests/webui/test_startup_cache.py::test_startup_cache_status_route tests/webui/test_startup_cache.py::test_startup_cache_stream_route -v
```

Expected: FAIL with 404 for `/api/startup-cache/status`.

- [ ] **Step 3: Create startup cache routes**

Create `api/routes/startup_cache.py`:

```python
"""Startup cache clear status routes."""

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from api.startup_cache import get_startup_cache_clearer, sse_json

router = APIRouter(prefix="/api/startup-cache", tags=["startup-cache"])


@router.get("/status")
def startup_cache_status(request: Request) -> dict:
    clearer = get_startup_cache_clearer(request)
    if clearer is None:
        raise HTTPException(status_code=503, detail="startup cache clearer not initialized")
    return clearer.snapshot()


@router.get("/stream")
def stream_startup_cache(request: Request) -> EventSourceResponse:
    clearer = get_startup_cache_clearer(request)
    if clearer is None:
        raise HTTPException(status_code=503, detail="startup cache clearer not initialized")

    def event_generator():
        for item in clearer.subscribe():
            yield sse_json(item)

    return EventSourceResponse(event_generator())
```

- [ ] **Step 4: Wire router and reset test state**

Modify `api/main.py` near the other `app.state` assignments:

```python
app.state.startup_cache_clearer = None  # StartupCacheClearer, created at startup
```

Modify `api/main.py` after the health router include:

```python
from api.routes import startup_cache as startup_cache_routes  # noqa: E402

app.include_router(startup_cache_routes.router)
```

Modify `tests/webui/conftest.py` inside the fixture before `with TestClient(...)`:

```python
    main.app.state.startup_cache_clearer = None
    main.DEFAULT_CONFIG["data_cache_dir"] = str(tmp_path / "cache")
```

This is required because FastAPI startup will run the cache clearer during tests; the test suite must only delete files inside the per-test temporary directory.

- [ ] **Step 5: Run route tests and verify they pass**

Run:

```bash
pytest tests/webui/test_startup_cache.py::test_startup_cache_status_route tests/webui/test_startup_cache.py::test_startup_cache_stream_route -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/main.py api/routes/startup_cache.py tests/webui/conftest.py tests/webui/test_startup_cache.py
git commit -m "feat(api): expose startup cache clear status"
```

---

### Task 3: Backend Gate and Scheduler Integration

**Files:**
- Modify: `api/main.py`
- Modify: `api/scheduler.py`
- Modify: `api/routes/analysis.py`
- Modify: `api/routes/queue.py`
- Test: `tests/webui/test_startup_cache.py`

- [ ] **Step 1: Add failing gate tests**

Append to `tests/webui/test_startup_cache.py`:

```python
def test_analysis_and_queue_block_until_startup_cache_completed(client, tmp_path):
    import api.main as main
    from api.startup_cache import StartupCacheClearer

    clearer = StartupCacheClearer(tmp_path / "cache")
    main.app.state.startup_cache_clearer = clearer

    analysis_resp = client.post(
        "/api/analysis",
        json={"ticker": "NVDA", "trade_date": "2024-05-10"},
    )
    queue_resp = client.post(
        "/api/queue",
        json={"tickers": ["NVDA"], "trade_date": "2024-05-10"},
    )

    assert analysis_resp.status_code == 503
    assert queue_resp.status_code == 503
    assert analysis_resp.json()["detail"] == "启动缓存清理未完成，暂不能开始分析"
    assert queue_resp.json()["detail"] == "启动缓存清理未完成，暂不能开始分析"

    clearer.run_sync()

    ok_resp = client.post(
        "/api/queue",
        json={"tickers": ["NVDA"], "trade_date": "2024-05-10"},
    )
    assert ok_resp.status_code == 200


def test_scheduler_does_not_advance_before_startup_cache_completed(tmp_path, monkeypatch):
    import api.main as main
    from api.scheduler import QueueScheduler
    from api.startup_cache import StartupCacheClearer
    from api.store import Store

    store = Store(tmp_path / "sched.db")
    monkeypatch.setattr(main, "get_store", lambda: store)
    store.enqueue_run(
        "r1",
        "NVDA",
        "2024-05-10",
        "stock",
        {"ticker": "NVDA", "trade_date": "2024-05-10"},
    )

    class App:
        pass

    app = App()
    app.state = type("State", (), {})()
    app.state.startup_cache_clearer = StartupCacheClearer(tmp_path / "cache")
    app.state.graph_factory = lambda req: (_ for _ in ()).throw(AssertionError("must not launch"))

    scheduler = QueueScheduler(app)

    assert scheduler.advance() is None
    assert store.get_status("r1") == "pending"
```

- [ ] **Step 2: Run gate tests and verify they fail**

Run:

```bash
pytest tests/webui/test_startup_cache.py::test_analysis_and_queue_block_until_startup_cache_completed tests/webui/test_startup_cache.py::test_scheduler_does_not_advance_before_startup_cache_completed -v
```

Expected: FAIL because routes do not call the gate and scheduler still advances.

- [ ] **Step 3: Gate analysis and queue routes**

Modify `api/routes/analysis.py`:

```python
from api.startup_cache import assert_startup_cache_ready
```

Add as the first line inside `start_analysis`:

```python
    assert_startup_cache_ready(request)
```

Modify `api/routes/queue.py`:

```python
from api.startup_cache import assert_startup_cache_ready
```

Add as the first line inside `enqueue`:

```python
    assert_startup_cache_ready(request)
```

- [ ] **Step 4: Gate scheduler**

Modify `api/scheduler.py` inside `advance`, after `store = self._store()` and before `if store.has_running_run()`:

```python
            clearer = getattr(self._app.state, "startup_cache_clearer", None)
            if clearer is not None and not clearer.is_ready():
                return None
```

- [ ] **Step 5: Start cache clear task at startup and advance after completion**

Modify `api/main.py` imports:

```python
from api.startup_cache import StartupCacheClearer
```

Modify `_wire_graph_factory()` after scheduler creation and before `reset_orphaned_runs()`:

```python
    if app.state.startup_cache_clearer is None:
        app.state.startup_cache_clearer = StartupCacheClearer(DEFAULT_CONFIG["data_cache_dir"])

    def _advance_after_cache_clear(state: dict) -> None:
        if state.get("status") == "completed" and app.state.scheduler is not None:
            app.state.scheduler.advance()

    app.state.startup_cache_clearer.start(on_complete=_advance_after_cache_clear)
```

Then keep `get_store().reset_orphaned_runs()` but leave `app.state.scheduler.advance()` in place. It will return early until the clearer is ready.

- [ ] **Step 6: Run gate tests and scheduler tests**

Run:

```bash
pytest tests/webui/test_startup_cache.py::test_analysis_and_queue_block_until_startup_cache_completed tests/webui/test_startup_cache.py::test_scheduler_does_not_advance_before_startup_cache_completed tests/webui/test_scheduler.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add api/main.py api/routes/analysis.py api/routes/queue.py api/scheduler.py tests/webui/test_startup_cache.py
git commit -m "feat(api): gate analysis on startup cache clear"
```

---

### Task 4: Frontend Types, API Helpers, and Formatting Helpers

**Files:**
- Modify: `webui/lib/types.ts`
- Modify: `webui/lib/api.ts`
- Create: `webui/lib/startup-cache.ts`
- Create: `webui/lib/startup-cache.test.ts`

- [ ] **Step 1: Add failing helper tests**

Create `webui/lib/startup-cache.test.ts`:

```typescript
import test from "node:test";
import assert from "node:assert/strict";
import { formatBytes, startupCacheToServiceItem, startupCacheReady } from "./startup-cache.ts";
import type { StartupCacheStatusDetail } from "./types.ts";

const state = (status: StartupCacheStatusDetail["status"]): StartupCacheStatusDetail => ({
  status,
  phase: status,
  message: status === "completed" ? "启动缓存清理完成" : "正在清理 endpoint 本地数据缓存",
  current_path: status === "running" ? "akshare/demo.pkl" : null,
  processed_items: status === "running" ? 2 : 3,
  total_items: 3,
  deleted_files: 2,
  released_bytes: 1536,
  errors: [],
  started_at: "2026-07-08T00:00:00Z",
  completed_at: status === "running" ? null : "2026-07-08T00:00:02Z",
  updated_at: "2026-07-08T00:00:02Z",
  cache_root: "/Users/me/.tradingagents/cache",
});

test("startupCacheReady is true only when completed", () => {
  assert.equal(startupCacheReady(state("completed")), true);
  assert.equal(startupCacheReady(state("running")), false);
  assert.equal(startupCacheReady(null), false);
});

test("formatBytes renders compact binary units", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(1536), "1.5 KB");
});

test("startupCacheToServiceItem converts running state to system item", () => {
  const item = startupCacheToServiceItem(state("running"));
  assert.equal(item.id, "system:startup-cache-clear");
  assert.equal(item.kind, "system");
  assert.equal(item.status, "checking");
  assert.match(item.message, /2\/3/);
  assert.match(item.message, /1.5 KB/);
});
```

- [ ] **Step 2: Run helper tests and verify they fail**

Run:

```bash
cd webui && npm test -- lib/startup-cache.test.ts
```

Expected: FAIL because `startup-cache.ts` and types do not exist.

- [ ] **Step 3: Add TypeScript startup cache types**

Modify `webui/lib/types.ts` after `ServiceHealthSummary`:

```typescript
export type StartupCacheStatus = "pending" | "running" | "completed" | "error";

export interface StartupCacheError {
  path: string;
  message: string;
}

export interface StartupCacheStatusDetail {
  status: StartupCacheStatus;
  phase: string;
  message: string;
  current_path: string | null;
  processed_items: number;
  total_items: number;
  deleted_files: number;
  released_bytes: number;
  errors: StartupCacheError[];
  started_at: string | null;
  completed_at: string | null;
  updated_at: string | null;
  cache_root: string;
}

export type StartupCacheEvent =
  | { event: "cache_clear_status"; data: StartupCacheStatusDetail }
  | { event: "summary"; data: StartupCacheStatusDetail };
```

- [ ] **Step 4: Add formatting helper**

Create `webui/lib/startup-cache.ts`:

```typescript
import type { ServiceHealthItem, StartupCacheStatusDetail } from "./types";

export const STARTUP_CACHE_ITEM_ID = "system:startup-cache-clear";

export function startupCacheReady(state: StartupCacheStatusDetail | null): boolean {
  return state?.status === "completed";
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${Number.isInteger(kb) ? kb : kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  return `${Number.isInteger(mb) ? mb : mb.toFixed(1)} MB`;
}

export function startupCacheToServiceItem(
  state: StartupCacheStatusDetail | null,
): ServiceHealthItem | null {
  if (!state) return null;
  const status: ServiceHealthItem["status"] =
    state.status === "completed" ? "ok" : state.status === "error" ? "error" : "checking";
  const progress =
    state.total_items > 0 ? `${state.processed_items}/${state.total_items}` : "扫描中";
  const released = formatBytes(state.released_bytes);
  const suffix =
    state.status === "completed"
      ? `${state.deleted_files} files · ${released}`
      : state.status === "error"
        ? `失败 ${state.errors.length} 个 · ${progress}`
        : `${progress} · ${state.deleted_files} files · ${released}`;

  return {
    id: STARTUP_CACHE_ITEM_ID,
    name: "启动维护",
    kind: "system",
    status,
    message: `${state.message} · ${suffix}`,
    latency_ms: null,
  };
}
```

- [ ] **Step 5: Add frontend API helpers**

Modify the import list in `webui/lib/api.ts` to include:

```typescript
  StartupCacheEvent,
  StartupCacheStatusDetail,
```

Add after `serviceHealthStreamUrl()`:

```typescript
export function startupCacheStatusUrl(): string {
  return `${BASE}/api/startup-cache/status`;
}

export function startupCacheStreamUrl(): string {
  return `${BASE}/api/startup-cache/stream`;
}

export async function getStartupCacheStatus(): Promise<StartupCacheStatusDetail> {
  const r = await fetch(startupCacheStatusUrl());
  if (!r.ok) throw new Error("无法加载启动缓存清理状态");
  return r.json();
}

export function subscribeStartupCacheClear(
  onEvent: (e: StartupCacheEvent) => void,
  onClose: () => void,
  onError: (message: string) => void,
): () => void {
  const es = new EventSource(startupCacheStreamUrl());
  const statusHandler = (ev: MessageEvent) => {
    try {
      onEvent({ event: "cache_clear_status", data: JSON.parse(ev.data) });
    } catch {
      /* ignore malformed */
    }
  };
  const summaryHandler = (ev: MessageEvent) => {
    try {
      onEvent({ event: "summary", data: JSON.parse(ev.data) });
    } catch {
      /* ignore malformed */
    } finally {
      es.close();
      onClose();
    }
  };
  es.addEventListener("cache_clear_status", statusHandler);
  es.addEventListener("summary", summaryHandler);
  es.onerror = () => {
    es.close();
    onError("启动缓存清理连接中断");
    onClose();
  };
  return () => es.close();
}
```

- [ ] **Step 6: Run frontend helper tests**

Run:

```bash
cd webui && npm test
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add webui/lib/types.ts webui/lib/api.ts webui/lib/startup-cache.ts webui/lib/startup-cache.test.ts
git commit -m "feat(webui): add startup cache status helpers"
```

---

### Task 5: Service Health UI and Analysis Control Gate

**Files:**
- Modify: `webui/components/ServiceHealthPanel.tsx`
- Modify: `webui/components/ConfigCard.tsx`
- Modify: `webui/components/QueuePanel.tsx`
- Modify: `webui/app/page.tsx`

- [ ] **Step 1: Modify ServiceHealthPanel props and rendering**

In `webui/components/ServiceHealthPanel.tsx`, update imports:

```typescript
import type { ServiceHealthItem, ServiceHealthSummary, StartupCacheStatusDetail } from "@/lib/types";
import { STARTUP_CACHE_ITEM_ID, formatBytes } from "@/lib/startup-cache";
```

Update the prop type block to include:

```typescript
  startupCacheStatus?: StartupCacheStatusDetail | null;
```

Add it to the function argument destructuring.

Inside the item map, before `return`, add:

```typescript
            const startupDetails =
              item.id === STARTUP_CACHE_ITEM_ID && startupCacheStatus ? startupCacheStatus : null;
```

After the existing `{item.message && ...}` block, add:

```tsx
              {startupDetails && (
                <div className="mt-2 space-y-1 font-mono text-xs leading-5 text-muted-foreground">
                  <div>
                    进度 {startupDetails.processed_items}/{startupDetails.total_items} · 删除{" "}
                    {startupDetails.deleted_files} 个文件 · 释放{" "}
                    {formatBytes(startupDetails.released_bytes)}
                  </div>
                  {startupDetails.current_path && (
                    <div className="break-words">当前：{startupDetails.current_path}</div>
                  )}
                  {startupDetails.errors.length > 0 && (
                    <div className="space-y-1 text-destructive">
                      {startupDetails.errors.map((err) => (
                        <div key={`${err.path}:${err.message}`} className="break-words">
                          {err.path}: {err.message}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
```

- [ ] **Step 2: Modify ConfigCard gate props**

In `webui/components/ConfigCard.tsx`, add props:

```typescript
  disabled = false,
  disabledReason = "",
```

Update the prop type:

```typescript
  disabled?: boolean;
  disabledReason?: string;
```

Update the submit button:

```tsx
          disabled={disabled || running || activeAnalysts.length === 0 || tickers.length === 0}
          title={disabled ? disabledReason : undefined}
```

Update the label expression:

```tsx
          {disabled
            ? "启动维护中"
            : running
              ? "分析进行中"
              : tickers.length > 1
                ? `分析 ${tickers.length} 个标的`
                : "开始分析"}
```

- [ ] **Step 3: Modify QueuePanel gate props**

In `webui/components/QueuePanel.tsx`, update the function destructuring:

```typescript
  disabled = false,
  disabledReason = "",
```

Add to prop type:

```typescript
  disabled?: boolean;
  disabledReason?: string;
```

Update the `清空` button with these exact attributes and class:

```tsx
            disabled={disabled}
            title={disabled ? disabledReason : undefined}
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-muted-foreground transition-colors hover:text-destructive focus-visible:outline-none focus-visible:border-primary disabled:cursor-not-allowed disabled:opacity-40"
```

Update the up button:

```tsx
                disabled={disabled || index === 0}
                title={disabled ? disabledReason : "上移"}
```

Update the down button:

```tsx
                disabled={disabled || index === pending.length - 1}
                title={disabled ? disabledReason : "下移"}
```

Update the remove button with these exact attributes and class:

```tsx
                disabled={disabled}
                title={disabled ? disabledReason : "移除"}
                className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-destructive disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:border-primary"
```

Leave the cancel-running button unchanged except for existing `canceling` behavior, because cancellation must remain available while startup cache clearing is running.

- [ ] **Step 4: Wire state in `webui/app/page.tsx`**

Update API imports:

```typescript
  getStartupCacheStatus,
  subscribeStartupCacheClear,
```

Update type imports:

```typescript
  StartupCacheStatusDetail,
```

Add helper import:

```typescript
import { startupCacheReady, startupCacheToServiceItem } from "@/lib/startup-cache";
```

Add refs/state near health refs:

```typescript
  const startupCacheUnsubscribeRef = useRef<(() => void) | null>(null);
  const [startupCacheStatus, setStartupCacheStatus] = useState<StartupCacheStatusDetail | null>(null);
  const [startupCacheError, setStartupCacheError] = useState<string | null>(null);
```

Add callback near health callbacks:

```typescript
  const watchStartupCache = useCallback(() => {
    startupCacheUnsubscribeRef.current?.();
    getStartupCacheStatus()
      .then((status) => {
        setStartupCacheStatus(status);
        setStartupCacheError(null);
        if (status.status === "completed" || status.status === "error") return;
        startupCacheUnsubscribeRef.current = subscribeStartupCacheClear(
          (event) => {
            setStartupCacheStatus(event.data);
            setStartupCacheError(null);
            if (event.data.status === "completed") {
              refreshQueue();
              refreshHistory();
            }
          },
          () => {
            startupCacheUnsubscribeRef.current = null;
          },
          (message) => {
            setStartupCacheError(message);
            window.setTimeout(() => {
              getStartupCacheStatus().then(setStartupCacheStatus).catch(() => {});
            }, 2000);
          },
        );
      })
      .catch((err) => setStartupCacheError((err as Error).message));
  }, []);
```

Call `watchStartupCache()` in the mount effect before service health:

```typescript
    watchStartupCache();
```

Add cleanup:

```typescript
      startupCacheUnsubscribeRef.current?.();
```

Compute UI gate near `sortedHealthItems`:

```typescript
  const startupItem = startupCacheToServiceItem(startupCacheStatus);
  const sortedHealthItems = sortServiceHealthItems([
    ...(startupItem ? [startupItem] : []),
    ...Object.values(healthItems),
  ]);
  const startupReady = startupCacheReady(startupCacheStatus);
  const startupGateReason =
    startupCacheError ||
    (startupReady ? "" : startupCacheStatus?.message ?? "启动缓存清理完成后可开始分析");
```

Pass to `ServiceHealthPanel`:

```tsx
                startupCacheStatus={startupCacheStatus}
```

Pass to `ConfigCard`:

```tsx
              options && (
                <ConfigCard
                  options={options}
                  onStart={onStart}
                  running={running}
                  disabled={!startupReady}
                  disabledReason={startupGateReason}
                />
              )
```

Pass to `QueuePanel`:

```tsx
              disabled={!startupReady}
              disabledReason={startupGateReason}
```

- [ ] **Step 5: Run TypeScript tests and lint**

Run:

```bash
cd webui && npm test && npm run lint
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webui/app/page.tsx webui/components/ServiceHealthPanel.tsx webui/components/ConfigCard.tsx webui/components/QueuePanel.tsx
git commit -m "feat(webui): show startup cache clear progress"
```

---

### Task 6: End-to-End Verification and Changelog

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add changelog entry**

Under `## [Unreleased]`, in the existing `### Added` section before the ETF news entry, add:

```markdown
- Clear endpoint local data caches on WebUI API startup, show startup maintenance progress in the Service Health area, and block new analysis runs until cache clearing succeeds.
```

- [ ] **Step 2: Run focused backend tests**

Run:

```bash
pytest tests/webui/test_startup_cache.py tests/webui/test_routes_analysis.py tests/webui/test_routes_queue.py tests/webui/test_scheduler.py -v
```

Expected: PASS.

- [ ] **Step 3: Run full non-integration Python test suite**

Run:

```bash
pytest -m "not integration"
```

Expected: PASS.

- [ ] **Step 4: Run frontend verification**

Run:

```bash
cd webui && npm test && npm run lint
```

Expected: PASS.

- [ ] **Step 5: Run manual smoke check**

Run:

```bash
./dev.sh
```

Open `http://localhost:3000` and verify:

- Service Health area shows `启动维护` during startup cache clear.
- Start analysis button is disabled until the startup task is completed.
- Queue panel remains readable.
- After completion, start analysis is enabled.
- If a test cache file exists under `~/.tradingagents/cache/akshare/`, it is deleted on API restart.
- A file under `~/.tradingagents/cache/checkpoints/` remains.

- [ ] **Step 6: Commit changelog and final fixes**

```bash
git add CHANGELOG.md
git commit -m "docs: update changelog for startup cache clear"
```

- [ ] **Step 7: Final status check**

Run:

```bash
git status --short
```

Expected: only unrelated pre-existing user changes remain, or a clean tree if no unrelated changes exist.
