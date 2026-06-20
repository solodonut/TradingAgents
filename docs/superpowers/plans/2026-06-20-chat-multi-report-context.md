# Chat Multi-Report Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Chat session persist and use an ordered selection of multiple completed analysis reports.

**Architecture:** Normalize Chat-to-analysis associations into `chat_session_runs` while preserving `chat_sessions.run_id` as a read-compatible legacy fallback. Validate report selections at the API boundary, assemble clearly separated report contexts in the stream route, and replace the right-sidebar single select with a controlled checkbox picker that saves changes to the active session.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, SQLite, pytest, Next.js 16, React 19, TypeScript, Tailwind CSS 4

---

## File Map

- Modify `api/schemas.py`: multi-report request and response fields.
- Modify `api/store.py`: normalized association table, compatibility reads, atomic replacement, cleanup.
- Modify `api/routes/chat.py`: validation, association update endpoint, multi-report prompt context.
- Modify `tests/webui/test_chat_store.py`: store migration and association behavior.
- Modify `tests/webui/test_routes_chat.py`: API validation and prompt-context behavior.
- Modify `webui/lib/types.ts`: expose `run_ids` on Chat sessions.
- Modify `webui/lib/api.ts`: create and update sessions with report arrays.
- Modify `webui/components/chat/RunPicker.tsx`: completed-only multi-select UI.
- Modify `webui/app/chat/page.tsx`: persist selection and recover from save failures.

### Task 1: Store Ordered Report Associations

**Files:**
- Modify: `api/store.py`
- Test: `tests/webui/test_chat_store.py`

- [ ] **Step 1: Write failing store tests**

Add tests that create real analysis rows and assert ordered associations, replacement with an empty list, legacy fallback, and cleanup:

```python
def _completed_run(store: Store, run_id: str, ticker: str) -> None:
    store.insert_run(run_id, ticker, "2026-06-20", "stock", {})
    store.complete_run(run_id, "Hold", {"market_report": f"{ticker} report"})


def test_chat_session_persists_ordered_run_ids(tmp_path):
    store = Store(tmp_path / "t.db")
    _completed_run(store, "r1", "AAA")
    _completed_run(store, "r2", "BBB")
    store.create_chat_session("s1", run_id=None, title="pair", run_ids=["r2", "r1"])
    assert store.get_chat_session("s1").run_ids == ["r2", "r1"]
    assert store.get_chat_session("s1").run_id == "r2"


def test_replace_chat_session_run_ids_accepts_empty_selection(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id="legacy", title=None)
    store.replace_chat_session_run_ids("s1", [])
    session = store.get_chat_session("s1")
    assert session.run_ids == []
    assert session.run_id is None


def test_legacy_chat_session_run_id_is_exposed_as_run_ids(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id="legacy", title=None)
    assert store.get_chat_session("s1").run_ids == ["legacy"]


def test_deleting_run_removes_chat_association(tmp_path):
    store = Store(tmp_path / "t.db")
    _completed_run(store, "r1", "AAA")
    store.create_chat_session("s1", run_id=None, title=None, run_ids=["r1"])
    store.delete_run("r1")
    assert store.get_chat_session("s1").run_ids == []
```

- [ ] **Step 2: Run the store tests and verify RED**

Run: `.venv/bin/python -m pytest tests/webui/test_chat_store.py -q`

Expected: FAIL because `run_ids`, the new constructor argument, and `replace_chat_session_run_ids` do not exist.

- [ ] **Step 3: Add the association schema and store methods**

Add this table to `_SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS chat_session_runs (
    session_id TEXT NOT NULL,
    run_id     TEXT NOT NULL,
    position   INTEGER NOT NULL,
    PRIMARY KEY (session_id, run_id)
);
```

Extend `create_chat_session` with `run_ids: list[str] | None = None`. When `run_ids is not None`, insert the session with a null legacy `run_id` and insert ordered rows. Add a transaction-scoped helper and replacement method:

```python
def _replace_chat_session_run_ids(
    self, conn: sqlite3.Connection, session_id: str, run_ids: list[str]
) -> None:
    conn.execute("DELETE FROM chat_session_runs WHERE session_id=?", (session_id,))
    conn.executemany(
        "INSERT INTO chat_session_runs (session_id, run_id, position) VALUES (?, ?, ?)",
        [(session_id, run_id, position) for position, run_id in enumerate(run_ids)],
    )
    conn.execute(
        "UPDATE chat_sessions SET run_id=NULL, updated_at=? WHERE session_id=?",
        (_now(), session_id),
    )

def replace_chat_session_run_ids(self, session_id: str, run_ids: list[str]) -> None:
    with self._lock, self._connect() as conn:
        self._replace_chat_session_run_ids(conn, session_id, run_ids)
```

Read association rows ordered by `position`, fall back to the legacy column only when no rows exist, and expose the first effective ID through `run_id`. Delete association rows from both `delete_chat_session` and `delete_run`.

- [ ] **Step 4: Run the store tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/webui/test_chat_store.py -q`

Expected: all store tests pass.

### Task 2: Define and Validate the Multi-Report API

**Files:**
- Modify: `api/schemas.py`
- Modify: `api/routes/chat.py`
- Test: `tests/webui/test_routes_chat.py`

- [ ] **Step 1: Write failing route tests for create and update**

Create completed, running, and errored analysis rows through the real test store. Cover successful ordered creation/update and rejection of missing, duplicate, and unfinished IDs:

```python
def _create_completed_run(store, run_id: str, ticker: str) -> None:
    store.insert_run(run_id, ticker, "2026-06-20", "stock", {})
    store.complete_run(run_id, "Hold", {"market_report": f"{ticker} report"})


def test_create_session_with_multiple_completed_reports(client):
    import api.main as main
    store = main.get_store()
    _create_completed_run(store, "r1", "AAA")
    _create_completed_run(store, "r2", "BBB")
    sid = client.post("/api/chat/sessions", json={"run_ids": ["r2", "r1"]}).json()["session_id"]
    session = client.get(f"/api/chat/sessions/{sid}").json()["session"]
    assert session["run_ids"] == ["r2", "r1"]
    assert session["run_id"] == "r2"


def test_update_session_reports_is_atomic(client):
    import api.main as main
    store = main.get_store()
    _create_completed_run(store, "r1", "AAA")
    sid = client.post("/api/chat/sessions", json={"run_ids": ["r1"]}).json()["session_id"]
    response = client.put(
        f"/api/chat/sessions/{sid}/reports",
        json={"run_ids": ["r1", "missing"]},
    )
    assert response.status_code == 422
    assert client.get(f"/api/chat/sessions/{sid}").json()["session"]["run_ids"] == ["r1"]
```

Use parameterized cases for duplicate IDs, a `running` run, and an `error` run, each expecting HTTP 422.

- [ ] **Step 2: Run route tests and verify RED**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_chat.py -q`

Expected: FAIL because the request schema ignores `run_ids`, responses omit it, and `/reports` returns 404/405.

- [ ] **Step 3: Add request and response schemas**

Add `run_ids` and legacy conflict validation:

```python
class ChatSessionCreate(BaseModel):
    run_id: str | None = None
    run_ids: list[str] | None = None

    @model_validator(mode="after")
    def _one_report_field(self) -> "ChatSessionCreate":
        if self.run_id is not None and self.run_ids is not None:
            raise ValueError("provide run_id or run_ids, not both")
        return self


class ChatSessionReportsUpdate(BaseModel):
    run_ids: list[str] = Field(default_factory=list)


class ChatSession(BaseModel):
    session_id: str
    run_id: str | None
    run_ids: list[str] = Field(default_factory=list)
    title: str | None
    created_at: str
    updated_at: str
```

Import `model_validator` from Pydantic.

- [ ] **Step 4: Add atomic API validation and the reports endpoint**

Add one route helper that rejects duplicates before reading runs and returns the corresponding completed run objects in order:

```python
def _completed_runs(store, run_ids: list[str]):
    if len(run_ids) != len(set(run_ids)):
        raise HTTPException(status_code=422, detail="run_ids must be unique")
    runs = []
    for run_id in run_ids:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=422, detail=f"analysis run not found: {run_id}")
        if run.status != "completed":
            raise HTTPException(status_code=422, detail=f"analysis run is not completed: {run_id}")
        runs.append(run)
    return runs
```

Use it before session creation and before calling `replace_chat_session_run_ids`. Preserve the existing legacy `run_id` create path, but require it to identify a completed run too. Add:

```python
@router.put("/sessions/{session_id}/reports")
def update_session_reports(
    session_id: str, req: ChatSessionReportsUpdate
) -> dict:
    store = get_store()
    if store.get_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    _completed_runs(store, req.run_ids)
    store.replace_chat_session_run_ids(session_id, req.run_ids)
    return store.get_chat_session(session_id).model_dump()
```

- [ ] **Step 5: Run route and store tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/webui/test_chat_store.py tests/webui/test_routes_chat.py -q`

Expected: all selected tests pass.

### Task 3: Assemble Multiple Reports in Chat Context

**Files:**
- Modify: `api/routes/chat.py`
- Test: `tests/webui/test_routes_chat.py`

- [ ] **Step 1: Write a failing stream-context test**

Monkeypatch `build_system_prompt` to capture the report context passed by the real stream route:

```python
def test_stream_chat_uses_all_selected_reports(client, monkeypatch):
    import api.main as main
    import api.routes.chat as chat_routes
    store = main.get_store()
    _create_completed_run(store, "r1", "AAA")
    _create_completed_run(store, "r2", "BBB")
    captured = {}

    def capture_prompt(report_context: str, holdings_ctx: str) -> str:
        captured["report_context"] = report_context
        return "system"

    monkeypatch.setattr(chat_routes, "build_system_prompt", capture_prompt)
    _install_fake_chat(client, [AIMessage(content="ok。不构成投资建议。")])
    sid = client.post("/api/chat/sessions", json={"run_ids": ["r2", "r1"]}).json()["session_id"]
    with client.stream("POST", f"/api/chat/sessions/{sid}/stream", json={"message": "比较"}) as stream:
        "".join(stream.iter_text())

    context = captured["report_context"]
    assert context.index("报告 1 · BBB") < context.index("报告 2 · AAA")
    assert "BBB report" in context
    assert "AAA report" in context
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_chat.py::test_stream_chat_uses_all_selected_reports -q`

Expected: FAIL because only `session.run_id` is rendered and no numbered separators exist.

- [ ] **Step 3: Implement ordered multi-report context assembly**

Add a focused helper and call it from `stream_chat`:

```python
def _report_context(store, run_ids: list[str]) -> str:
    if not run_ids:
        return build_report_context(None, None, "标的")
    sections = []
    for index, run_id in enumerate(run_ids, start=1):
        run = store.get_run(run_id)
        if run is None or run.status != "completed":
            continue
        header = f"# 报告 {index} · {run.ticker} · {run.trade_date} · {run.decision or '—'}"
        sections.append(
            f"{header}\n\n{build_report_context(run.result, run.decision, run.ticker)}"
        )
    return "\n\n---\n\n".join(sections) or build_report_context(None, None, "标的")
```

Replace the single `session.run_id` branch with `_report_context(store, session.run_ids)`.

- [ ] **Step 4: Run the targeted and full route tests**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_chat.py -q`

Expected: all route tests pass.

### Task 4: Add Frontend Types and API Calls

**Files:**
- Modify: `webui/lib/types.ts`
- Modify: `webui/lib/api.ts`

- [ ] **Step 1: Update the session type**

Add the persisted array while retaining the compatibility field:

```typescript
export interface ChatSessionT {
  session_id: string;
  run_id: string | null;
  run_ids: string[];
  title: string | null;
  created_at: string;
  updated_at: string;
}
```

- [ ] **Step 2: Update create and association APIs**

Change session creation to accept an array and add atomic replacement:

```typescript
export async function createChatSession(runIds: string[]): Promise<string> {
  const r = await fetch(`${BASE}/api/chat/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_ids: runIds }),
  });
  if (!r.ok) throw new Error("failed to create chat session");
  return (await r.json()).session_id as string;
}

export async function updateChatSessionReports(
  id: string,
  runIds: string[],
): Promise<ChatSessionT> {
  const r = await fetch(`${BASE}/api/chat/sessions/${id}/reports`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_ids: runIds }),
  });
  if (!r.ok) throw new Error("无法保存关联分析报告");
  return r.json();
}
```

- [ ] **Step 3: Run frontend type checking to expose incomplete consumers**

Run: `cd webui && npx tsc --noEmit`

Expected: FAIL at `page.tsx` because it still passes a scalar report ID.

### Task 5: Replace the Single Report Picker with Multi-Select

**Files:**
- Modify: `webui/components/chat/RunPicker.tsx`
- Modify: `webui/app/chat/page.tsx`

- [ ] **Step 1: Implement the controlled report picker**

Change props to `value: string[]`, `onChange: (runIds: string[]) => void`, and `disabled?: boolean`. Keep all history rows visible. Render a compact disclosure button showing `通用咨询` or `已选择 N 份报告`, followed by a bounded `ios-scrollbar` list when open. Each row uses a checkbox; set `disabled={run.status !== "completed" || disabled}` and show the status text for unavailable rows.

The toggle operation must preserve history order:

```typescript
const toggleRun = (runId: string) => {
  onChange(
    value.includes(runId)
      ? value.filter((id) => id !== runId)
      : [...value, runId],
  );
};
```

- [ ] **Step 2: Persist report selection in the active page**

Replace scalar `runId` state with `runIds`. On session open, use `data.session.run_ids`. Create new sessions with the current array. Save existing-session changes optimistically and roll back on failure:

```typescript
const changeReports = async (nextRunIds: string[]) => {
  const previous = runIds;
  setRunIds(nextRunIds);
  setReportError(null);
  if (!sessionId) return;
  setSavingReports(true);
  try {
    await updateChatSessionReports(sessionId, nextRunIds);
    await refreshSessions();
  } catch (error) {
    setRunIds(previous);
    setReportError(error instanceof Error ? error.message : "无法保存关联分析报告");
  } finally {
    setSavingReports(false);
  }
};
```

Pass `disabled={streaming || savingReports}` to `RunPicker`, render `reportError` directly beneath it, and derive the generic current title from `currentSession?.run_ids.length` instead of `run_id`.

- [ ] **Step 3: Run TypeScript and lint checks**

Run: `cd webui && npx tsc --noEmit`

Expected: PASS.

Run: `cd webui && npm run lint`

Expected: PASS.

### Task 6: Full Verification

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run focused backend tests**

Run: `.venv/bin/python -m pytest tests/webui/test_chat_store.py tests/webui/test_routes_chat.py tests/webui/test_routes_history.py -q`

Expected: all selected tests pass.

- [ ] **Step 2: Run focused Python lint**

Run: `.venv/bin/ruff check api/schemas.py api/store.py api/routes/chat.py tests/webui/test_chat_store.py tests/webui/test_routes_chat.py`

Expected: `All checks passed!`

- [ ] **Step 3: Run frontend verification**

Run: `cd webui && npx tsc --noEmit`

Expected: PASS.

Run: `cd webui && npm run lint`

Expected: PASS.

Run: `cd webui && npm run build`

Expected: production build completes. If the sandbox blocks Google Fonts, report that network-only limitation separately and do not treat lint/type-check success as a successful build.

- [ ] **Step 4: Check the final diff**

Run: `git diff --check`

Expected: no whitespace errors. Confirm every changed production line traces to multi-report Chat context or the already-present Chat history changes in the dirty worktree.
