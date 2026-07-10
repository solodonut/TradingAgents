# Manual Full Cache Clear Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a WebUI user delete every file below the configured data-cache directory, including checkpoints, from a confirmed action and an API.

**Architecture:** Extend the existing `StartupCacheClearer` with an explicit `include_checkpoints` flag while retaining its safe default. A process-local manual clearer, exposed by new FastAPI routes, uses full mode and streams the existing progress state. The WebUI starts and watches that clearer from Service Health after a destructive confirmation.

**Tech Stack:** Python 3.10+, FastAPI, sse-starlette, pytest, Next.js 16, React 19, TypeScript, Node test runner.

---

## File Structure

- Modify `api/startup_cache.py`: make checkpoint exclusion configurable and use neutral task labels for progress messages.
- Create `api/routes/cache.py`: start, inspect, and stream the manual full-clear task.
- Modify `api/main.py`: add the process-local `manual_cache_clearer` state and register the router.
- Modify `tests/webui/conftest.py`: reset manual clearer state for each API test.
- Modify `tests/webui/test_startup_cache.py`: cover full-mode deletion while retaining startup-mode checkpoint preservation.
- Create `tests/webui/test_routes_cache.py`: cover start/status/SSE and conflict behavior.
- Modify `webui/lib/types.ts`: add manual cache-clear aliases using the existing state shape.
- Modify `webui/lib/api.ts`: add manual cache clear request/status/SSE helpers.
- Modify `webui/components/ServiceHealthPanel.tsx`: render the confirmed full-clear action and progress.
- Modify `webui/app/page.tsx`: own confirmation, manual state, and SSE lifecycle.

### Task 1: Add full mode to the reusable clearer

**Files:**
- Modify: `api/startup_cache.py`
- Modify: `tests/webui/test_startup_cache.py`

- [ ] **Step 1: Write a failing full-mode deletion test**

```python
def test_startup_cache_clearer_full_mode_deletes_checkpoints(tmp_path):
    from api.startup_cache import StartupCacheClearer

    cache_root = tmp_path / "cache"
    vendor_cache = cache_root / "tushare" / "fund_daily.pkl"
    checkpoint = cache_root / "checkpoints" / "510330.db"
    vendor_cache.parent.mkdir(parents=True)
    checkpoint.parent.mkdir(parents=True)
    vendor_cache.write_bytes(b"market-cache")
    checkpoint.write_bytes(b"resume-state")

    clearer = StartupCacheClearer(cache_root, include_checkpoints=True)
    clearer.run_sync()

    assert clearer.snapshot()["status"] == "completed"
    assert not vendor_cache.exists()
    assert not checkpoint.exists()
```

- [ ] **Step 2: Verify the test fails because the constructor has no full-mode option**

Run: `pytest tests/webui/test_startup_cache.py::test_startup_cache_clearer_full_mode_deletes_checkpoints -v`

Expected: `TypeError` mentioning `include_checkpoints`.

- [ ] **Step 3: Add the minimal mode flag without changing startup behavior**

```python
class StartupCacheClearer:
    def __init__(
        self,
        cache_root: str | Path,
        *,
        include_checkpoints: bool = False,
        max_errors: int = 20,
    ):
        self.cache_root = Path(cache_root).expanduser()
        self._cache_root_resolved = self.cache_root.resolve(strict=False)
        self.include_checkpoints = include_checkpoints
        self.max_errors = max_errors
        self._state = StartupCacheState()
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue[dict | None]] = []
        self._thread: threading.Thread | None = None
        self._running = False
        self._on_complete = None
        self._error_count = 0

    def _is_excluded(self, path: Path) -> bool:
        try:
            rel = path.relative_to(self.cache_root)
        except ValueError:
            return True
        return not self.include_checkpoints and rel.parts[:1] == ("checkpoints",)
```

Keep the existing symlink-root and symlink-target checks untouched.

- [ ] **Step 4: Verify default and full modes**

Run: `pytest tests/webui/test_startup_cache.py -v`

Expected: all startup cache tests pass; the existing checkpoint-preservation test still passes.

- [ ] **Step 5: Commit the focused backend behavior**

```bash
git add api/startup_cache.py tests/webui/test_startup_cache.py
git commit -m "feat(cache): support full cache clear mode"
```

### Task 2: Add manual cache-clear API and state

**Files:**
- Create: `api/routes/cache.py`
- Modify: `api/main.py`
- Modify: `tests/webui/conftest.py`
- Create: `tests/webui/test_routes_cache.py`

- [ ] **Step 1: Write failing route tests**

```python
def test_manual_cache_clear_starts_full_mode(client, tmp_path, monkeypatch):
    import api.main as main

    checkpoint = tmp_path / "cache" / "checkpoints" / "510330.db"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"resume")

    response = client.post("/api/cache/clear")

    assert response.status_code == 200
    assert response.json()["status"] in {"running", "completed"}
    assert not checkpoint.exists()
    assert main.app.state.manual_cache_clearer.snapshot()["status"] == "completed"


def test_manual_cache_clear_rejects_active_analysis(client):
    import api.main as main

    main.app.state.run_lock.acquire()
    try:
        response = client.post("/api/cache/clear")
    finally:
        main.app.state.run_lock.release()

    assert response.status_code == 409
    assert response.json()["detail"] == "分析运行中，无法清除缓存"
```

- [ ] **Step 2: Verify the new route tests fail with 404**

Run: `pytest tests/webui/test_routes_cache.py -v`

Expected: both tests fail because `/api/cache/clear` is not registered.

- [ ] **Step 3: Initialize and register the manual clearer**

In `api/main.py`, add state before router setup and include the new router:

```python
app.state.manual_cache_clearer = None

from api.routes import cache as cache_routes  # noqa: E402
app.include_router(cache_routes.router)
```

In `tests/webui/conftest.py`, reset `main.app.state.manual_cache_clearer = None` alongside startup state.

- [ ] **Step 4: Implement the routes with existing state/SSE conventions**

```python
router = APIRouter(prefix="/api/cache", tags=["cache"])

def _clearer(request: Request) -> StartupCacheClearer:
    clearer = getattr(request.app.state, "manual_cache_clearer", None)
    if clearer is None:
        clearer = StartupCacheClearer(
            DEFAULT_CONFIG["data_cache_dir"], include_checkpoints=True
        )
        request.app.state.manual_cache_clearer = clearer
    return clearer

@router.post("/clear")
def clear_cache(request: Request) -> dict:
    if request.app.state.run_lock.locked():
        raise HTTPException(status_code=409, detail="分析运行中，无法清除缓存")
    clearer = _clearer(request)
    if clearer.is_active():
        raise HTTPException(status_code=409, detail="缓存清理正在进行")
    clearer.start()
    return clearer.snapshot()

@router.get("/status")
def cache_status(request: Request) -> dict:
    return _clearer(request).snapshot()

@router.get("/stream")
def cache_stream(request: Request) -> EventSourceResponse:
    def event_generator():
        for item in _clearer(request).subscribe():
            yield sse_json(item)
    return EventSourceResponse(event_generator())
```

Expose `is_active()` as a small public wrapper around the existing locked activity check. Do not let `GET` allocate a clearing thread; it may only allocate the idle state holder.

- [ ] **Step 5: Add status, stream, and concurrent-clear tests**

```python
def test_manual_cache_status_is_idle_before_first_clear(client):
    response = client.get("/api/cache/status")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_manual_cache_stream_emits_terminal_summary(client):
    client.post("/api/cache/clear")
    with client.stream("GET", "/api/cache/stream") as stream:
        body = "".join(stream.iter_text())
    assert "event: cache_clear_status" in body
    assert "event: summary" in body
```

Use a blocked `_scan_targets()` fixture to prove a second POST returns 409 while a first clear is active.

- [ ] **Step 6: Run the API tests**

Run: `pytest tests/webui/test_routes_cache.py tests/webui/test_startup_cache.py -v`

Expected: PASS.

- [ ] **Step 7: Commit the API surface**

```bash
git add api/main.py api/routes/cache.py api/startup_cache.py tests/webui/conftest.py tests/webui/test_routes_cache.py
git commit -m "feat(api): add manual full cache clear routes"
```

### Task 3: Add frontend API helpers and manual clear state

**Files:**
- Modify: `webui/lib/types.ts`
- Modify: `webui/lib/api.ts`
- Modify: `webui/app/page.tsx`

- [ ] **Step 1: Write a failing helper contract test**

Create `webui/lib/manual-cache.test.ts`:

```ts
import test from "node:test";
import assert from "node:assert/strict";
import { manualCacheStatusUrl } from "./api.ts";

test("manualCacheStatusUrl uses the manual cache endpoint", () => {
  assert.match(manualCacheStatusUrl(), /\/api\/cache\/status$/);
});
```

- [ ] **Step 2: Verify it fails because the helper is absent**

Run: `cd webui && node --no-warnings --test --experimental-strip-types lib/manual-cache.test.ts`

Expected: TypeScript/module error that `manualCacheStatusUrl` is not exported.

- [ ] **Step 3: Add manual API helpers using the existing status shape**

In `webui/lib/types.ts`:

```ts
export type ManualCacheStatusDetail = StartupCacheStatusDetail;
export type ManualCacheEvent = StartupCacheEvent;
```

In `webui/lib/api.ts`:

```ts
export function manualCacheStatusUrl(): string {
  return `${BASE}/api/cache/status`;
}

export function manualCacheStreamUrl(): string {
  return `${BASE}/api/cache/stream`;
}

export async function clearAllCaches(): Promise<ManualCacheStatusDetail> {
  const r = await fetch(`${BASE}/api/cache/clear`, { method: "POST" });
  if (r.status === 409) throw new Error(await r.text());
  if (!r.ok) throw new Error("清除缓存失败");
  return r.json();
}
```

Implement `subscribeManualCacheClear` with this complete event contract:

```ts
export function subscribeManualCacheClear(
  onEvent: (event: ManualCacheEvent) => void,
  onClose: () => void,
  onError: (message: string) => void,
): () => void {
  const es = new EventSource(manualCacheStreamUrl());
  const status = (ev: MessageEvent) => {
    try {
      onEvent({ event: "cache_clear_status", data: JSON.parse(ev.data) });
    } catch {
      // malformed SSE payloads are ignored
    }
  };
  const summary = (ev: MessageEvent) => {
    try {
      onEvent({ event: "summary", data: JSON.parse(ev.data) });
    } catch {
      // malformed SSE payloads are ignored
    } finally {
      es.close();
      onClose();
    }
  };
  es.addEventListener("cache_clear_status", status);
  es.addEventListener("summary", summary);
  es.onerror = () => {
    es.close();
    onError("缓存清理连接中断");
    onClose();
  };
  return () => es.close();
}
```

- [ ] **Step 4: Add page state and lifecycle**

Add `manualCacheStatus`, `manualCacheError`, and a manual subscription ref. On successful POST, set the returned state and subscribe until terminal completion. On a completed event, refresh queue/history; on an error event, preserve the error state. Clean up the subscription in the existing page unmount effect.

- [ ] **Step 5: Run frontend helper tests**

Run: `cd webui && node --no-warnings --test --experimental-strip-types lib/manual-cache.test.ts lib/startup-cache.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit the API client wiring**

```bash
git add webui/lib/types.ts webui/lib/api.ts webui/lib/manual-cache.test.ts webui/app/page.tsx
git commit -m "feat(webui): wire manual cache clear API"
```

### Task 4: Add confirmed full-clear control and progress UI

**Files:**
- Modify: `webui/components/ServiceHealthPanel.tsx`
- Modify: `webui/app/page.tsx`

- [ ] **Step 1: Write a failing UI-state helper test**

Create a pure helper so the button behavior remains testable without adding a new browser test framework:

```ts
import test from "node:test";
import assert from "node:assert/strict";
import { manualCacheActionDisabled } from "./manual-cache.ts";

test("manual cache action is disabled only during an active clear", () => {
  assert.equal(manualCacheActionDisabled(null), false);
  assert.equal(manualCacheActionDisabled({ status: "running" }), true);
  assert.equal(manualCacheActionDisabled({ status: "completed" }), false);
});
```

- [ ] **Step 2: Verify it fails because the props/control do not exist**

Run: `cd webui && node --no-warnings --test --experimental-strip-types lib/manual-cache.test.ts`

Expected: module error because `manualCacheActionDisabled` is not exported.

- [ ] **Step 3: Add narrow UI props and action**

Extend the panel props:

```tsx
manualCacheStatus?: StartupCacheStatusDetail | null;
manualCacheError?: string | null;
onClearAllCaches?: () => void;
```

Define and use the helper in `webui/lib/manual-cache.ts`:

```ts
export function manualCacheActionDisabled(
  state: Pick<StartupCacheStatusDetail, "status"> | null,
): boolean {
  return state?.status === "running";
}
```

Render a destructive button beside `检查`:

```tsx
<button
  type="button"
  onClick={onClearAllCaches}
  disabled={!onClearAllCaches || manualCacheActionDisabled(manualCacheStatus ?? null)}
  className="glass-control inline-flex h-7 items-center gap-1.5 rounded-md border-destructive/50 px-2 font-mono text-[0.68rem] text-destructive disabled:cursor-not-allowed disabled:opacity-70"
>
  {manualCacheStatus?.status === "running" ? "清理中" : "清除全部缓存"}
</button>
```

Below the expanded health details, render manual status counters and bounded errors using the same `formatBytes` helper already used for startup state.

- [ ] **Step 4: Implement page-level confirmation**

```tsx
const clearAllCachesWithConfirmation = useCallback(() => {
  const confirmed = window.confirm(
    "将删除所有市场数据缓存和 checkpoints，已中断分析无法恢复。分析历史、队列、持仓快照和记忆不会删除。是否继续？",
  );
  if (!confirmed) return;
  clearAllCaches()
    .then((state) => {
      setManualCacheStatus(state);
      setManualCacheError(null);
      watchManualCache();
    })
    .catch((err) => setManualCacheError((err as Error).message));
}, [watchManualCache]);
```

Pass this callback and manual state into `ServiceHealthPanel`. Do not call it automatically.

- [ ] **Step 5: Run frontend checks**

Run: `cd webui && node --no-warnings --test --experimental-strip-types lib/manual-cache.test.ts && npm run lint`

Expected: tests and lint pass.

- [ ] **Step 6: Commit the WebUI control**

```bash
git add webui/components/ServiceHealthPanel.tsx webui/app/page.tsx webui/lib/manual-cache.test.ts
git commit -m "feat(webui): add full cache clear control"
```

### Task 5: Full verification

**Files:**
- Verify: changed backend and frontend files

- [ ] **Step 1: Run focused backend tests**

Run: `pytest tests/webui/test_startup_cache.py tests/webui/test_routes_cache.py -v`

Expected: PASS.

- [ ] **Step 2: Run the WebUI test and static checks**

Run: `cd webui && node --no-warnings --test --experimental-strip-types lib/manual-cache.test.ts lib/startup-cache.test.ts && npm run lint`

Expected: PASS.

- [ ] **Step 3: Run repository lint and relevant regression suite**

Run: `ruff check api tradingagents tests/webui && pytest tests/webui/ -m unit`

Expected: PASS.

- [ ] **Step 4: Inspect the final diff**

Run: `git diff --check HEAD~3..HEAD && git status --short`

Expected: no whitespace errors and only intended files changed.
