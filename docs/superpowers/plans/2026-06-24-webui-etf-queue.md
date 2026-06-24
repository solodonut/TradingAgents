# WebUI ETF 队列分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 WebUI 一次输入多个标的代码、持久化为后端队列，由调度器串行依次分析，出错跳过、可管理队列。

**Architecture:** 所有运行统一走「入队（pending）→ 独立调度器 `QueueScheduler.advance()` 启动 → runner 线程结束后回调 advance 推进」一条路径，单个标的即长度为 1 的队列。队列持久化在现有 SQLite `analysis_runs` 表（新增 `queue_position` 列与 `pending` 状态）。前端多代码输入 + 新增 QueuePanel，SSE「跟随当前 running」。

**Tech Stack:** Python 3.10+ / FastAPI / SQLite（`api/`）；Next.js 16 + React 19 + Tailwind 4（`webui/`）；pytest（无 CI，手动跑 lint+test）。

## Global Constraints

- Python 命令一律用 `.venv/bin/python`（系统 python 可能 <3.10 或 NumPy 1.x，会崩）。
- 收尾必须手动跑：`.venv/bin/python -m ruff check .` 与 `.venv/bin/python -m pytest -m "not integration"`（无 CI 兜底）。
- 单用户串行不变量：同一时刻至多一个 `running`。
- 提交规范：Conventional Commits（`feat(scope):` / `test(scope):` / `docs(scope):`），同步维护 `CHANGELOG.md`（Keep a Changelog）。
- 改 `webui/` 前先读 `webui/node_modules/next/dist/docs/`（Next.js 16 与训练数据有破坏性差异），遵守 `webui/AGENTS.md`。
- 回复用户一律中文。
- 设计来源：`docs/superpowers/specs/2026-06-24-webui-etf-queue-design.md`。

---

## File Structure

**后端（`api/`）**
- `api/schemas.py`（改）：`RunStatus` 加 `pending`；新增 `EnqueueRequest` / `QueueItem` / `QueueState` / `ReorderRequest`。
- `api/store.py`（改）：迁移加列 + 队列方法 + `list_runs` 排除 pending + 重启复位。
- `api/scheduler.py`（建）：`QueueScheduler`。
- `api/routes/queue.py`（建）：队列接口。
- `api/routes/analysis.py`（改）：`POST /api/analysis` 改为入队+调度，去掉忙时 409。
- `api/main.py`（改）：创建并挂载 scheduler，启动时复位孤儿 + advance；注册 queue 路由。

**测试（`tests/webui/`）**
- `test_store.py`（改）：队列 store 方法单测。
- `test_scheduler.py`（建）：调度推进 / 出错跳过 / 取消推进。
- `test_routes_queue.py`（建）：队列接口 + gated fake。
- `test_routes_analysis.py`（改）：替换 409 测试为「入队」测试。
- `test_smoke.py`（改）：queue 路由注册。
- `conftest.py`（改）：重置 `app.state.scheduler`。

**前端（`webui/`）**
- `lib/types.ts`（改）：`RunStatus` 加 `pending`；新增 `QueueItem` / `QueueState`。
- `lib/api.ts`（改）：`enqueueAnalysis` / `getQueue` / `removeQueueItem` / `clearQueue` / `reorderQueue`。
- `components/QueuePanel.tsx`（建）：队列面板。
- `components/ConfigCard.tsx`（改）：多代码输入。
- `app/page.tsx`（改）：队列 state + 轮询 + SSE 跟随 + 渲染 QueuePanel。

**文档**
- `CHANGELOG.md`（改）、`AGENTS.md`（改）。

---

## Task 1: Schemas — pending 状态与队列契约

**Files:**
- Modify: `api/schemas.py:10`（RunStatus）, 追加新模型
- Test: `tests/webui/test_schemas.py`

**Interfaces:**
- Produces:
  - `RunStatus = Literal["pending","running","completed","error","cancelled"]`
  - `class EnqueueRequest(BaseModel)`: `tickers: list[str]`, `trade_date: str`, `asset_type: AssetType="stock"`, `analysts: list[AnalystName]=...`, `research_depth: Literal[1,3,5]=3`, `output_language: str="Chinese"`, `llm_provider: str|None=None`, `deep_think_llm: str|None=None`, `quick_think_llm: str|None=None`；校验器 `_at_least_one_ticker`（去空白、转大写、去重后非空）、`_at_least_one_analyst`。
  - `class QueueItem(BaseModel)`: `run_id: str`, `ticker: str`, `status: RunStatus`, `queue_position: int|None`, `created_at: str`
  - `class QueueState(BaseModel)`: `running: QueueItem|None`, `pending: list[QueueItem]`
  - `class ReorderRequest(BaseModel)`: `ordered_run_ids: list[str]`

- [ ] **Step 1: 写失败测试**

在 `tests/webui/test_schemas.py` 末尾追加：

```python
def test_enqueue_request_normalizes_tickers():
    from api.schemas import EnqueueRequest

    req = EnqueueRequest(tickers=[" nvda ", "AAPL", "nvda", ""], trade_date="2024-05-10")
    assert req.tickers == ["NVDA", "AAPL"]


def test_enqueue_request_rejects_empty_tickers():
    import pytest
    from pydantic import ValidationError
    from api.schemas import EnqueueRequest

    with pytest.raises(ValidationError):
        EnqueueRequest(tickers=[" ", ""], trade_date="2024-05-10")


def test_queue_state_shape():
    from api.schemas import QueueItem, QueueState

    item = QueueItem(
        run_id="r1", ticker="NVDA", status="pending",
        queue_position=1, created_at="2024-05-10T00:00:00+00:00",
    )
    state = QueueState(running=None, pending=[item])
    assert state.pending[0].ticker == "NVDA"
    assert state.running is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_schemas.py -q`
Expected: FAIL（`ImportError: cannot import name 'EnqueueRequest'`）

- [ ] **Step 3: 实现**

`api/schemas.py` 第 10 行改为：

```python
RunStatus = Literal["pending", "running", "completed", "error", "cancelled"]
```

在 `AnalysisRequest` 类定义之后追加：

```python
class EnqueueRequest(BaseModel):
    tickers: list[str]
    trade_date: str
    asset_type: AssetType = "stock"
    analysts: list[AnalystName] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"]
    )
    research_depth: Literal[1, 3, 5] = 3
    output_language: str = "Chinese"
    llm_provider: str | None = None
    deep_think_llm: str | None = None
    quick_think_llm: str | None = None

    @field_validator("tickers")
    @classmethod
    def _at_least_one_ticker(cls, v: list[str]) -> list[str]:
        seen: list[str] = []
        for raw in v:
            t = raw.strip().upper()
            if t and t not in seen:
                seen.append(t)
        if not seen:
            raise ValueError("at least one ticker is required")
        return seen

    @field_validator("analysts")
    @classmethod
    def _at_least_one_analyst(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("at least one analyst is required")
        return v


class QueueItem(BaseModel):
    run_id: str
    ticker: str
    status: RunStatus
    queue_position: int | None
    created_at: str


class QueueState(BaseModel):
    running: QueueItem | None
    pending: list[QueueItem]


class ReorderRequest(BaseModel):
    ordered_run_ids: list[str]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_schemas.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/schemas.py tests/webui/test_schemas.py
git commit -m "feat(webui): add pending status and queue schemas"
```

---

## Task 2: Store — 迁移、队列方法、重启复位

**Files:**
- Modify: `api/store.py`（import、`__init__` 迁移、`list_runs` 过滤、新增方法）
- Test: `tests/webui/test_store.py`

**Interfaces:**
- Consumes: `RunStatus`, `QueueItem`, `QueueState`（Task 1）；现有 `RunResult`、`_dumps`、`_now`。
- Produces（`Store` 新方法）：
  - `enqueue_run(run_id: str, ticker: str, trade_date: str, asset_type: str, config: dict) -> None`（插入 `status='pending'`，`queue_position = max(pending)+1`）
  - `start_run(run_id: str) -> bool`（`pending`→`running`，置空 `queue_position`；行数>0 为真）
  - `next_pending() -> RunResult | None`（`queue_position ASC` 最小）
  - `list_queue() -> QueueState`
  - `remove_pending(run_id: str) -> bool`
  - `clear_pending() -> int`
  - `reorder_pending(ordered_run_ids: list[str]) -> None`
  - `reset_orphaned_runs() -> int`（`running`→`error`）
  - `list_runs()` 修改为排除 `pending`

- [ ] **Step 1: 写失败测试**

在 `tests/webui/test_store.py` 末尾追加：

```python
def test_enqueue_and_next_pending_orders_by_position(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "q.db")
    store.enqueue_run("a", "NVDA", "2024-05-10", "stock", {"ticker": "NVDA"})
    store.enqueue_run("b", "AAPL", "2024-05-10", "stock", {"ticker": "AAPL"})

    nxt = store.next_pending()
    assert nxt.run_id == "a"
    assert nxt.config["ticker"] == "NVDA"


def test_start_run_flips_pending_to_running(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "q.db")
    store.enqueue_run("a", "NVDA", "2024-05-10", "stock", {})
    assert store.start_run("a") is True
    assert store.start_run("a") is False  # no longer pending
    assert store.get_status("a") == "running"
    assert store.has_running_run() is True


def test_list_queue_returns_running_and_ordered_pending(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "q.db")
    store.enqueue_run("a", "NVDA", "2024-05-10", "stock", {})
    store.enqueue_run("b", "AAPL", "2024-05-10", "stock", {})
    store.enqueue_run("c", "TSLA", "2024-05-10", "stock", {})
    store.start_run("a")

    state = store.list_queue()
    assert state.running.run_id == "a"
    assert [p.ticker for p in state.pending] == ["AAPL", "TSLA"]


def test_remove_pending_only_removes_pending(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "q.db")
    store.enqueue_run("a", "NVDA", "2024-05-10", "stock", {})
    store.start_run("a")
    store.enqueue_run("b", "AAPL", "2024-05-10", "stock", {})

    assert store.remove_pending("b") is True
    assert store.remove_pending("a") is False  # running, untouched
    assert store.get_status("a") == "running"


def test_clear_pending_leaves_running(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "q.db")
    store.enqueue_run("a", "NVDA", "2024-05-10", "stock", {})
    store.start_run("a")
    store.enqueue_run("b", "AAPL", "2024-05-10", "stock", {})
    store.enqueue_run("c", "TSLA", "2024-05-10", "stock", {})

    assert store.clear_pending() == 2
    assert store.list_queue().running.run_id == "a"
    assert store.list_queue().pending == []


def test_reorder_pending(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "q.db")
    store.enqueue_run("a", "NVDA", "2024-05-10", "stock", {})
    store.enqueue_run("b", "AAPL", "2024-05-10", "stock", {})
    store.enqueue_run("c", "TSLA", "2024-05-10", "stock", {})

    store.reorder_pending(["c", "a", "b"])
    assert [p.run_id for p in store.list_queue().pending] == ["c", "a", "b"]


def test_reset_orphaned_runs_marks_running_error(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "q.db")
    store.insert_run("a", "NVDA", "2024-05-10", "stock", {})  # status=running
    assert store.has_running_run() is True

    assert store.reset_orphaned_runs() == 1
    assert store.get_status("a") == "error"
    assert store.has_running_run() is False


def test_list_runs_excludes_pending(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "q.db")
    store.insert_run("a", "NVDA", "2024-05-10", "stock", {})  # running -> shown
    store.enqueue_run("b", "AAPL", "2024-05-10", "stock", {})  # pending -> hidden

    ids = {r.run_id for r in store.list_runs()}
    assert ids == {"a"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_store.py -q`
Expected: FAIL（`AttributeError: 'Store' object has no attribute 'enqueue_run'`）

- [ ] **Step 3: 实现**

`api/store.py` 顶部 import 块（第 10-17 行）加入 `QueueItem`, `QueueState`：

```python
from api.schemas import (
    ChatMessage,
    ChatSession,
    HistorySummary,
    PortfolioHolding,
    QueueItem,
    QueueState,
    RunResult,
    SessionProfile,
)
```

在 `Store.__init__` 的 `with self._connect() as conn:` 块内，`executescript` 之后追加迁移：

```python
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(analysis_runs)")}
            if "queue_position" not in cols:
                conn.execute("ALTER TABLE analysis_runs ADD COLUMN queue_position INTEGER")
```

把 `get_run` 里构造 `RunResult` 的部分抽成私有方法（DRY，供 `next_pending` 复用）。在 `get_run` 上方新增：

```python
    def _to_run_result(self, row: sqlite3.Row) -> RunResult:
        return RunResult(
            run_id=row["run_id"],
            ticker=row["ticker"],
            trade_date=row["trade_date"],
            asset_type=row["asset_type"],
            decision=row["decision"],
            status=row["status"],
            config=json.loads(row["config_json"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )
```

并把 `get_run` 的返回改为 `return self._to_run_result(row)`（替换原本内联的 `RunResult(...)`）。

`list_runs` 的 SQL（第 191-194 行）加过滤：

```python
            rows = conn.execute(
                "SELECT run_id, ticker, trade_date, decision, status, created_at "
                "FROM analysis_runs WHERE status != 'pending' "
                "ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
```

在 `has_running_run` 之后追加队列方法：

```python
    def _to_queue_item(self, row: sqlite3.Row) -> QueueItem:
        return QueueItem(
            run_id=row["run_id"],
            ticker=row["ticker"],
            status=row["status"],
            queue_position=row["queue_position"],
            created_at=row["created_at"],
        )

    def enqueue_run(
        self, run_id: str, ticker: str, trade_date: str, asset_type: str, config: dict
    ) -> None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(queue_position), 0) AS m "
                "FROM analysis_runs WHERE status='pending'"
            ).fetchone()
            pos = row["m"] + 1
            conn.execute(
                "INSERT INTO analysis_runs "
                "(run_id, ticker, trade_date, asset_type, decision, status, "
                " config_json, result_json, created_at, completed_at, queue_position) "
                "VALUES (?, ?, ?, ?, NULL, 'pending', ?, NULL, ?, NULL, ?)",
                (run_id, ticker, trade_date, asset_type, _dumps(config), _now(), pos),
            )

    def start_run(self, run_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE analysis_runs SET status='running', queue_position=NULL "
                "WHERE run_id=? AND status='pending'",
                (run_id,),
            )
            return cur.rowcount > 0

    def next_pending(self) -> RunResult | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_runs WHERE status='pending' "
                "ORDER BY queue_position ASC, rowid ASC LIMIT 1"
            ).fetchone()
        return None if row is None else self._to_run_result(row)

    def list_queue(self) -> QueueState:
        with self._connect() as conn:
            running_row = conn.execute(
                "SELECT run_id, ticker, status, queue_position, created_at "
                "FROM analysis_runs WHERE status='running' "
                "ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            pending_rows = conn.execute(
                "SELECT run_id, ticker, status, queue_position, created_at "
                "FROM analysis_runs WHERE status='pending' "
                "ORDER BY queue_position ASC, rowid ASC"
            ).fetchall()
        return QueueState(
            running=self._to_queue_item(running_row) if running_row else None,
            pending=[self._to_queue_item(r) for r in pending_rows],
        )

    def remove_pending(self, run_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM analysis_runs WHERE run_id=? AND status='pending'",
                (run_id,),
            )
            return cur.rowcount > 0

    def clear_pending(self) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM analysis_runs WHERE status='pending'")
            return cur.rowcount

    def reorder_pending(self, ordered_run_ids: list[str]) -> None:
        with self._lock, self._connect() as conn:
            pending = {
                r["run_id"]
                for r in conn.execute(
                    "SELECT run_id FROM analysis_runs WHERE status='pending'"
                )
            }
            pos = 1
            for run_id in ordered_run_ids:
                if run_id in pending:
                    conn.execute(
                        "UPDATE analysis_runs SET queue_position=? "
                        "WHERE run_id=? AND status='pending'",
                        (pos, run_id),
                    )
                    pos += 1

    def reset_orphaned_runs(self) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE analysis_runs SET status='error', result_json=?, completed_at=? "
                "WHERE status='running'",
                (_dumps({"error": "服务重启中断"}), _now()),
            )
            return cur.rowcount
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_store.py -q`
Expected: PASS（全部，含原有 store 测试）

- [ ] **Step 5: 提交**

```bash
git add api/store.py tests/webui/test_store.py
git commit -m "feat(webui): add queue persistence to store with migration"
```

---

## Task 3: Scheduler — 串行调度器

**Files:**
- Create: `api/scheduler.py`
- Test: `tests/webui/test_scheduler.py`

**Interfaces:**
- Consumes: `app.state.graph_factory`、`app.state.queues`、`app.state.cancellations`、`app.state.telemetry`、`app.state.starting_telemetry`（dict/None）；`AnalysisRunner`（`api/runner.py`）；`AnalysisRequest`（schemas）；`RunTelemetry`（`api/telemetry.py`）；`api.main.get_store`。
- Produces:
  - `class QueueScheduler(app)`：`advance() -> str | None`（启动下一个 pending，返回其 run_id；无则 None）。runner 线程结束后在 `finally` 自动回调 `advance()`。

- [ ] **Step 1: 写失败测试**

`tests/webui/test_scheduler.py`（新建）：

```python
import threading
import time
import types

import pytest

from api.scheduler import QueueScheduler
from api.store import Store


def _wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class _FakeApp:
    """Minimal stand-in for FastAPI app with the state attrs scheduler touches."""

    def __init__(self, store, graph_factory):
        self._store = store
        self.state = types.SimpleNamespace(
            graph_factory=graph_factory,
            queues={},
            cancellations={},
            telemetry={},
            starting_telemetry=None,
        )


def _instant_factory(chunks_by_ticker):
    """graph_factory whose stream yields preset chunks then ends, per ticker."""

    def factory(req):
        chunks = chunks_by_ticker.get(req.ticker, [])

        class _Inner:
            def stream(inner_self, init_state, **kwargs):
                yield from chunks

        graph = types.SimpleNamespace(graph=_Inner())
        return graph, {}, "Hold", {"final_trade_decision": "**Rating**: Hold"}

    return factory


@pytest.fixture()
def scheduler_env(tmp_path, monkeypatch):
    store = Store(tmp_path / "sched.db")
    import api.main as main

    monkeypatch.setattr(main, "get_store", lambda: store)
    return store, main


def test_advance_starts_first_pending_and_chains(scheduler_env):
    store, main = scheduler_env
    factory = _instant_factory(
        {
            "NVDA": [{"market_report": "m"}, {"final_trade_decision": "**Rating**: Hold"}],
            "AAPL": [{"market_report": "m"}, {"final_trade_decision": "**Rating**: Hold"}],
        }
    )
    app = _FakeApp(store, factory)
    sched = QueueScheduler(app)

    store.enqueue_run("a", "NVDA", "2024-05-10", "stock", {"ticker": "NVDA", "trade_date": "2024-05-10"})
    store.enqueue_run("b", "AAPL", "2024-05-10", "stock", {"ticker": "AAPL", "trade_date": "2024-05-10"})

    sched.advance()

    assert _wait_until(lambda: store.get_status("a") == "completed")
    assert _wait_until(lambda: store.get_status("b") == "completed")


def test_advance_skips_failing_run(scheduler_env):
    store, main = scheduler_env

    def factory(req):
        if req.ticker == "BAD":
            class _Boom:
                def stream(inner_self, init_state, **kwargs):
                    raise RuntimeError("kaboom")
                    yield  # pragma: no cover

            return types.SimpleNamespace(graph=_Boom()), {}, None, None

        class _Ok:
            def stream(inner_self, init_state, **kwargs):
                yield {"final_trade_decision": "**Rating**: Hold"}

        return types.SimpleNamespace(graph=_Ok()), {}, "Hold", {"final_trade_decision": "x"}

    app = _FakeApp(store, factory)
    sched = QueueScheduler(app)

    store.enqueue_run("bad", "BAD", "2024-05-10", "stock", {"ticker": "BAD", "trade_date": "2024-05-10"})
    store.enqueue_run("ok", "OK", "2024-05-10", "stock", {"ticker": "OK", "trade_date": "2024-05-10"})

    sched.advance()

    assert _wait_until(lambda: store.get_status("bad") == "error")
    assert _wait_until(lambda: store.get_status("ok") == "completed")


def test_cancel_then_advance_starts_next(scheduler_env):
    store, main = scheduler_env
    gate = threading.Event()

    def factory(req):
        if req.ticker == "FIRST":
            class _Gated:
                def stream(inner_self, init_state, **kwargs):
                    yield {"market_report": "m"}
                    gate.wait(timeout=3)
                    yield {"news_report": "n"}

            return types.SimpleNamespace(graph=_Gated()), {}, None, None

        class _Ok:
            def stream(inner_self, init_state, **kwargs):
                yield {"final_trade_decision": "**Rating**: Hold"}

        return types.SimpleNamespace(graph=_Ok()), {}, "Hold", {"final_trade_decision": "x"}

    app = _FakeApp(store, factory)
    sched = QueueScheduler(app)

    store.enqueue_run("f", "FIRST", "2024-05-10", "stock", {"ticker": "FIRST", "trade_date": "2024-05-10"})
    store.enqueue_run("s", "SECOND", "2024-05-10", "stock", {"ticker": "SECOND", "trade_date": "2024-05-10"})

    sched.advance()
    assert _wait_until(lambda: store.get_status("f") == "running")

    # cancel the first: set its cancel event + mark cancelled, then release the gate
    app.state.cancellations["f"].set()
    store.cancel_run("f", "cancelled by user")
    gate.set()

    assert _wait_until(lambda: store.get_status("f") == "cancelled")
    assert _wait_until(lambda: store.get_status("s") == "completed")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_scheduler.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'api.scheduler'`）

- [ ] **Step 3: 实现**

`api/scheduler.py`（新建）：

```python
"""Serial queue scheduler: starts the next pending run when idle."""

import queue as queue_mod
import threading

from api.runner import AnalysisRunner
from api.schemas import AnalysisRequest
from api.telemetry import RunTelemetry


class QueueScheduler:
    """Starts pending runs one at a time. ``advance`` is the single entry point.

    Called after enqueue and from each runner thread's finally; a lock keeps two
    runs from starting at once. ``advance`` loops past runs that fail to launch
    (e.g. graph build error), marking them error and trying the next.
    """

    def __init__(self, app):
        self._app = app
        self._lock = threading.Lock()

    def _store(self):
        from api.main import get_store

        return get_store()

    def advance(self) -> str | None:
        with self._lock:
            store = self._store()
            if store.has_running_run():
                return None
            while True:
                nxt = store.next_pending()
                if nxt is None:
                    return None
                if not store.start_run(nxt.run_id):
                    continue  # lost a race; try the next pending
                try:
                    self._launch(nxt)
                    return nxt.run_id
                except Exception as exc:  # noqa: BLE001 - bad config/build: skip it
                    store.mark_error(nxt.run_id, f"failed to start: {exc}")
                    continue

    def _launch(self, run) -> None:
        app = self._app
        req = AnalysisRequest(**run.config)

        telemetry = RunTelemetry(run.run_id)
        app.state.telemetry[run.run_id] = telemetry
        app.state.starting_telemetry = telemetry
        try:
            graph, init_state, decision, final_state = app.state.graph_factory(req)
        finally:
            app.state.starting_telemetry = None

        q: queue_mod.Queue = queue_mod.Queue()
        app.state.queues[run.run_id] = q
        cancel_event = threading.Event()
        app.state.cancellations[run.run_id] = cancel_event

        runner = AnalysisRunner(
            store=self._store(),
            event_queue=q,
            cancel_event=cancel_event,
            telemetry=telemetry,
        )

        def _target():
            try:
                runner.run(
                    run_id=run.run_id,
                    graph=graph,
                    init_state=init_state,
                    decision=decision,
                    final_state=final_state,
                )
            finally:
                self.advance()

        threading.Thread(target=_target, daemon=True).start()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_scheduler.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/scheduler.py tests/webui/test_scheduler.py
git commit -m "feat(webui): add serial queue scheduler"
```

---

## Task 4: 接入 main.py + 改造 analysis 路由

**Files:**
- Modify: `api/main.py`（state、startup、注册 queue 路由）
- Modify: `api/routes/analysis.py`（`start_analysis` 改为入队+调度，去掉 409）
- Modify: `tests/webui/conftest.py`（重置 scheduler）
- Modify: `tests/webui/test_routes_analysis.py`（替换 409 测试）

**Interfaces:**
- Consumes: `QueueScheduler`（Task 3）；`store.enqueue_run` / `reset_orphaned_runs`（Task 2）。
- Produces: `app.state.scheduler: QueueScheduler`；`POST /api/analysis` 行为变为「入队单个 + advance」，返回 `{"run_id": <running 或第一个>}`。

- [ ] **Step 1: 改 conftest + 替换 409 测试（写期望）**

`tests/webui/conftest.py` 在 `main.app.state.starting_telemetry = None` 之后加一行：

```python
    main.app.state.scheduler = None  # re-created by startup against fresh state
```

`tests/webui/test_routes_analysis.py`：删除 `test_second_analysis_while_running_returns_409` 整个函数，替换为：

```python
def test_post_analysis_while_running_enqueues_instead_of_409(client):
    import api.main as main

    # an already-running row makes the scheduler keep the new POST pending
    store = main.get_store()
    store.insert_run("busy", "NVDA", "2024-05-10", "stock", {})

    _install_fake_graph(client, chunks=[], decision="Hold", final_state={})
    resp = client.post(
        "/api/analysis", json={"ticker": "AAPL", "trade_date": "2024-05-10"}
    )
    assert resp.status_code == 200
    new_id = resp.json()["run_id"]
    assert store.get_status(new_id) == "pending"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_analysis.py -q`
Expected: FAIL（新测试断言 `pending` 失败 / 旧逻辑仍返回 409 路径不存在该 run）

- [ ] **Step 3: 实现 main.py**

`api/main.py` 第 39 行附近的 state 区块追加：

```python
app.state.scheduler = None  # QueueScheduler, created at startup; tests reset to None
```

把 startup 钩子 `_wire_graph_factory`（第 182 行）改为：

```python
@app.on_event("startup")
def _wire_graph_factory():
    if app.state.graph_factory is None:
        app.state.graph_factory = real_graph_factory
    if app.state.chat_llm_factory is None:
        app.state.chat_llm_factory = real_chat_llm_factory
    if app.state.scheduler is None:
        from api.scheduler import QueueScheduler

        app.state.scheduler = QueueScheduler(app)
    # recover from a crash mid-run, then resume any leftover queue
    get_store().reset_orphaned_runs()
    app.state.scheduler.advance()
    if _startup_model_check_enabled():
        _run_model_health_check()
```

注册 queue 路由（在 `analysis_routes` 注册之后，第 110 行附近追加）：

```python
from api.routes import queue as queue_routes  # noqa: E402

app.include_router(queue_routes.router)
```

> 说明：`queue_routes` 在 Task 5 创建。本步可先加 import，但若 Task 5 尚未完成会导致 import 失败——按计划顺序执行时 Task 5 紧随其后；若分批执行，先完成 Task 5 的文件创建再回到此 import。为安全起见，本步骤先**不**加这两行，留到 Task 5 Step 3 一并加入。

（因此本步实际只改 state 与 startup 两处；queue 路由注册移至 Task 5。）

- [ ] **Step 4: 实现 analysis 路由**

`api/routes/analysis.py` 的 `start_analysis`（第 28-76 行）整体替换为：

```python
@router.post("")
def start_analysis(req: AnalysisRequest, request: Request) -> dict:
    from api.main import get_store

    store = get_store()
    run_id = uuid.uuid4().hex
    store.enqueue_run(
        run_id=run_id,
        ticker=req.ticker,
        trade_date=req.trade_date,
        asset_type=req.asset_type,
        config=req.model_dump(),
    )
    request.app.state.scheduler.advance()
    return {"run_id": run_id}
```

删除该文件中不再使用的 import（`queue`、`threading`、`AnalysisRunner`、`RunTelemetry`）——确认 `cancel`/`stream`/`status` 仍需 `queue`（`stream_analysis` 用到 `queue.Empty`）。因此**保留** `import queue`，删除 `import threading`、`from api.runner import AnalysisRunner`、`from api.telemetry import RunTelemetry`（cancel 路由不再 set 新 event，只读 `app.state.cancellations`）。

> `cancel_analysis` 保持不变（仍设置已存在的 cancel_event、`cancel_run`、推 cancelled+None 关闭 SSE）。**不**在 cancel 路由调用 `advance()`——推进交由 runner 线程结束后的 finally 完成（见设计 §7）。

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_analysis.py -q`
Expected: PASS（含原有 stream/cancel/status/report 测试）

- [ ] **Step 6: 提交**

```bash
git add api/main.py api/routes/analysis.py tests/webui/conftest.py tests/webui/test_routes_analysis.py
git commit -m "feat(webui): route single analysis through queue scheduler"
```

---

## Task 5: 队列接口路由

**Files:**
- Create: `api/routes/queue.py`
- Modify: `api/main.py`（注册 queue 路由）
- Test: `tests/webui/test_routes_queue.py`
- Modify: `tests/webui/test_smoke.py`（queue 路由注册）

**Interfaces:**
- Consumes: `EnqueueRequest` / `ReorderRequest` / `QueueState` / `AnalysisRequest`（schemas）；`store` 队列方法；`request.app.state.scheduler.advance()`。
- Produces 路由（`prefix="/api/queue"`）：
  - `POST ""` → `{run_ids: list[str], running_run_id: str|None, queue: QueueState}`
  - `GET ""` → `QueueState`
  - `DELETE "/{run_id}"` → 204；非 pending → 409
  - `DELETE ""` → `{removed: int}`
  - `PATCH "/order"` → `QueueState`

- [ ] **Step 1: 写失败测试**

`tests/webui/test_routes_queue.py`（新建）：

```python
import threading
import time


def _wait_until(client, predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _install_gated_graph(client, gate: threading.Event):
    """First-launched run hangs on the gate; lets us inspect a pending backlog."""
    import api.main as main

    def factory(req):
        class _Inner:
            def stream(inner_self, init_state, **kwargs):
                yield {"market_report": "m"}
                gate.wait(timeout=5)
                yield {"final_trade_decision": "**Rating**: Hold"}

        return main.__dict__  # placeholder, replaced below

    # build a proper graph object
    def real_factory(req):
        class _Inner:
            def stream(inner_self, init_state, **kwargs):
                yield {"market_report": "m"}
                gate.wait(timeout=5)
                yield {"final_trade_decision": "**Rating**: Hold"}

        import types

        return types.SimpleNamespace(graph=_Inner()), {}, "Hold", {"final_trade_decision": "x"}

    main.app.state.graph_factory = real_factory


def test_enqueue_returns_running_and_pending(client):
    import api.main as main

    gate = threading.Event()
    _install_gated_graph(client, gate)

    resp = client.post(
        "/api/queue",
        json={"tickers": ["NVDA", "AAPL", "TSLA"], "trade_date": "2024-05-10"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["run_ids"]) == 3
    assert body["running_run_id"] is not None

    # first is running, other two pending
    assert _wait_until(client, lambda: main.get_store().list_queue().running is not None)
    state = main.get_store().list_queue()
    assert state.running.ticker == "NVDA"
    assert [p.ticker for p in state.pending] == ["AAPL", "TSLA"]

    gate.set()


def test_get_queue(client):
    gate = threading.Event()
    _install_gated_graph(client, gate)
    client.post("/api/queue", json={"tickers": ["NVDA", "AAPL"], "trade_date": "2024-05-10"})

    resp = client.get("/api/queue")
    assert resp.status_code == 200
    assert resp.json()["running"]["ticker"] == "NVDA"
    gate.set()


def test_delete_pending_item(client):
    import api.main as main

    gate = threading.Event()
    _install_gated_graph(client, gate)
    body = client.post(
        "/api/queue", json={"tickers": ["NVDA", "AAPL", "TSLA"], "trade_date": "2024-05-10"}
    ).json()
    pending_id = body["run_ids"][1]  # AAPL

    resp = client.delete(f"/api/queue/{pending_id}")
    assert resp.status_code == 204
    assert pending_id not in {p.run_id for p in main.get_store().list_queue().pending}
    gate.set()


def test_delete_running_item_returns_409(client):
    gate = threading.Event()
    _install_gated_graph(client, gate)
    body = client.post(
        "/api/queue", json={"tickers": ["NVDA", "AAPL"], "trade_date": "2024-05-10"}
    ).json()
    running_id = body["running_run_id"]

    resp = client.delete(f"/api/queue/{running_id}")
    assert resp.status_code == 409
    gate.set()


def test_clear_queue_keeps_running(client):
    import api.main as main

    gate = threading.Event()
    _install_gated_graph(client, gate)
    client.post(
        "/api/queue", json={"tickers": ["NVDA", "AAPL", "TSLA"], "trade_date": "2024-05-10"}
    )

    resp = client.delete("/api/queue")
    assert resp.status_code == 200
    assert resp.json()["removed"] == 2
    assert main.get_store().list_queue().pending == []
    assert main.get_store().list_queue().running is not None
    gate.set()


def test_reorder_queue(client):
    gate = threading.Event()
    _install_gated_graph(client, gate)
    body = client.post(
        "/api/queue", json={"tickers": ["NVDA", "AAPL", "TSLA"], "trade_date": "2024-05-10"}
    ).json()
    a, b, c = body["run_ids"]  # NVDA(running), AAPL, TSLA

    resp = client.patch("/api/queue/order", json={"ordered_run_ids": [c, b]})
    assert resp.status_code == 200
    assert [p["run_id"] for p in resp.json()["pending"]] == [c, b]
    gate.set()
```

> 注：`_install_gated_graph` 里第一个 `factory` 占位定义是误写，删掉它，只保留 `real_factory` 那段并直接赋给 `main.app.state.graph_factory`。实现时按下方「干净版」写。

干净版 helper（替换上面 `_install_gated_graph`）：

```python
def _install_gated_graph(client, gate: threading.Event):
    import types
    import api.main as main

    def factory(req):
        class _Inner:
            def stream(inner_self, init_state, **kwargs):
                yield {"market_report": "m"}
                gate.wait(timeout=5)
                yield {"final_trade_decision": "**Rating**: Hold"}

        return types.SimpleNamespace(graph=_Inner()), {}, "Hold", {"final_trade_decision": "x"}

    main.app.state.graph_factory = factory
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_queue.py -q`
Expected: FAIL（`/api/queue` 404，路由未注册）

- [ ] **Step 3: 实现路由 + 注册**

`api/routes/queue.py`（新建）：

```python
"""Queue routes: enqueue a batch, inspect, remove, clear, reorder."""

import uuid

from fastapi import APIRouter, HTTPException, Request, Response

from api.schemas import AnalysisRequest, EnqueueRequest, QueueState, ReorderRequest

router = APIRouter(prefix="/api/queue", tags=["queue"])


@router.post("")
def enqueue(req: EnqueueRequest, request: Request) -> dict:
    from api.main import get_store

    store = get_store()
    shared = req.model_dump(exclude={"tickers"})
    run_ids: list[str] = []
    for ticker in req.tickers:
        run_id = uuid.uuid4().hex
        analysis = AnalysisRequest(ticker=ticker, **shared)
        store.enqueue_run(
            run_id=run_id,
            ticker=ticker,
            trade_date=req.trade_date,
            asset_type=req.asset_type,
            config=analysis.model_dump(),
        )
        run_ids.append(run_id)

    request.app.state.scheduler.advance()
    queue = store.list_queue()
    return {
        "run_ids": run_ids,
        "running_run_id": queue.running.run_id if queue.running else None,
        "queue": queue.model_dump(),
    }


@router.get("", response_model=QueueState)
def get_queue() -> QueueState:
    from api.main import get_store

    return get_store().list_queue()


@router.delete("/{run_id}", status_code=204)
def remove_item(run_id: str) -> Response:
    from api.main import get_store

    if not get_store().remove_pending(run_id):
        raise HTTPException(status_code=409, detail="run is not pending")
    return Response(status_code=204)


@router.delete("")
def clear_queue() -> dict:
    from api.main import get_store

    return {"removed": get_store().clear_pending()}


@router.patch("/order", response_model=QueueState)
def reorder(req: ReorderRequest) -> QueueState:
    from api.main import get_store

    store = get_store()
    store.reorder_pending(req.ordered_run_ids)
    return store.list_queue()
```

`api/main.py` 在 `app.include_router(analysis_routes.router)` 之后追加：

```python
from api.routes import queue as queue_routes  # noqa: E402

app.include_router(queue_routes.router)
```

`tests/webui/test_smoke.py` 在 `test_chat_routes_registered` 之后追加：

```python
@pytest.mark.smoke
def test_queue_routes_registered():
    from api.main import app

    client = TestClient(app)
    assert client.get("/api/queue").status_code == 200
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_queue.py tests/webui/test_smoke.py -q`
Expected: PASS

- [ ] **Step 5: 全量后端验证 + 提交**

Run: `.venv/bin/python -m ruff check . && .venv/bin/python -m pytest -m "not integration" -q`
Expected: ruff 0 error；pytest 全绿（integration 自动跳过）

```bash
git add api/routes/queue.py api/main.py tests/webui/test_routes_queue.py tests/webui/test_smoke.py
git commit -m "feat(webui): add queue management endpoints"
```

---

## Task 6: 前端类型与 API helper

**Files:**
- Modify: `webui/lib/types.ts`
- Modify: `webui/lib/api.ts`

**Interfaces:**
- Produces:
  - `RunStatus` 增加 `"pending"`。
  - `interface QueueItem { run_id: string; ticker: string; status: RunStatus; queue_position: number | null; created_at: string }`
  - `interface QueueState { running: QueueItem | null; pending: QueueItem[] }`
  - `enqueueAnalysis(req): Promise<{ run_ids: string[]; running_run_id: string | null; queue: QueueState }>`
  - `getQueue(): Promise<QueueState>`
  - `removeQueueItem(runId): Promise<void>`（409→抛错）
  - `clearQueue(): Promise<number>`
  - `reorderQueue(orderedRunIds): Promise<QueueState>`

- [ ] **Step 1: 先读 Next 文档约束**

Run: `ls "webui/node_modules/next/dist/docs/"`
说明：本任务仅改 `lib/`（纯 TS，无 Next API），但遵循 `webui/AGENTS.md` 要求先确认无相关破坏性变更后再动 `webui/`。

- [ ] **Step 2: 改 types.ts**

`webui/lib/types.ts` 第 3 行：

```typescript
export type RunStatus = "pending" | "running" | "completed" | "error" | "cancelled";
```

在 `HistorySummary` 接口之后追加：

```typescript
export interface QueueItem {
  run_id: string;
  ticker: string;
  status: RunStatus;
  queue_position: number | null;
  created_at: string;
}

export interface QueueState {
  running: QueueItem | null;
  pending: QueueItem[];
}
```

- [ ] **Step 3: 改 api.ts**

`webui/lib/api.ts` import 块加入 `QueueState`：

```typescript
import type {
  AnalysisRequest,
  ChatMessageT,
  ChatSessionT,
  ConfigOptions,
  HistorySummary,
  PortfolioHolding,
  QueueState,
  RunResult,
  RunStatusDetail,
  SessionProfile,
} from "./types";
```

在 `startAnalysis` 之后追加：

```typescript
export interface EnqueueRequest {
  tickers: string[];
  trade_date: string;
  asset_type: AnalysisRequest["asset_type"];
  analysts: string[];
  research_depth: 1 | 3 | 5;
  output_language: string;
  llm_provider: string | null;
  deep_think_llm: string | null;
  quick_think_llm: string | null;
}

export async function enqueueAnalysis(
  req: EnqueueRequest,
): Promise<{ run_ids: string[]; running_run_id: string | null; queue: QueueState }> {
  const r = await fetch(`${BASE}/api/queue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error("无法加入分析队列");
  return r.json();
}

export async function getQueue(): Promise<QueueState> {
  const r = await fetch(`${BASE}/api/queue`);
  return r.ok ? r.json() : { running: null, pending: [] };
}

export async function removeQueueItem(runId: string): Promise<void> {
  const r = await fetch(`${BASE}/api/queue/${runId}`, { method: "DELETE" });
  if (r.status === 409) throw new Error("该项已在分析中，无法移除");
  if (!r.ok && r.status !== 204) throw new Error("移除排队项失败");
}

export async function clearQueue(): Promise<number> {
  const r = await fetch(`${BASE}/api/queue`, { method: "DELETE" });
  if (!r.ok) throw new Error("清空队列失败");
  return (await r.json()).removed as number;
}

export async function reorderQueue(orderedRunIds: string[]): Promise<QueueState> {
  const r = await fetch(`${BASE}/api/queue/order`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ordered_run_ids: orderedRunIds }),
  });
  if (!r.ok) throw new Error("调整顺序失败");
  return r.json();
}
```

- [ ] **Step 4: 类型检查**

Run: `cd webui && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 5: 提交**

```bash
git add webui/lib/types.ts webui/lib/api.ts
git commit -m "feat(webui): add queue types and api helpers"
```

---

## Task 7: QueuePanel 组件

**Files:**
- Create: `webui/components/QueuePanel.tsx`

**Interfaces:**
- Consumes: `QueueState`（types），`removeQueueItem` / `clearQueue` / `reorderQueue`（api）。
- Produces: `<QueuePanel queue onRemove onClear onReorder onCancelRunning canceling />`
  - props: `queue: QueueState`，`onRemove(runId: string): void`，`onClear(): void`，`onReorder(orderedRunIds: string[]): void`，`onCancelRunning(runId: string): void`，`canceling: boolean`。

- [ ] **Step 1: 实现组件**

`webui/components/QueuePanel.tsx`（新建）：

```tsx
"use client";
import { ChevronDown, ChevronUp, ListOrdered, OctagonX, Trash2, X } from "lucide-react";
import type { QueueState } from "@/lib/types";

export function QueuePanel({
  queue,
  onRemove,
  onClear,
  onReorder,
  onCancelRunning,
  canceling = false,
}: {
  queue: QueueState;
  onRemove: (runId: string) => void;
  onClear: () => void;
  onReorder: (orderedRunIds: string[]) => void;
  onCancelRunning: (runId: string) => void;
  canceling?: boolean;
}) {
  const pending = queue.pending;
  const hasItems = queue.running !== null || pending.length > 0;
  if (!hasItems) return null;

  const move = (index: number, delta: number) => {
    const next = [...pending];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onReorder(next.map((p) => p.run_id));
  };

  return (
    <div className="glass rounded-lg px-3 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
          <ListOrdered className="size-3.5" aria-hidden="true" />
          分析队列
        </div>
        {pending.length > 0 && (
          <button
            type="button"
            onClick={onClear}
            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-muted-foreground transition-colors hover:text-destructive focus-visible:outline-none focus-visible:border-primary"
          >
            <Trash2 className="size-3" aria-hidden="true" />
            清空
          </button>
        )}
      </div>

      <ul className="mt-2 space-y-1.5">
        {queue.running && (
          <li className="thinking-panel flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5">
            <span className="truncate font-mono text-sm text-foreground">
              {queue.running.ticker}
            </span>
            <span className="flex items-center gap-2">
              <span className="font-mono text-[0.6rem] uppercase tracking-[0.14em] text-amber-300">
                运行中
              </span>
              <button
                type="button"
                onClick={() => onCancelRunning(queue.running!.run_id)}
                disabled={canceling}
                aria-label="停止当前分析"
                className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-destructive disabled:opacity-50 focus-visible:outline-none focus-visible:border-primary"
              >
                <OctagonX className="size-3.5" aria-hidden="true" />
              </button>
            </span>
          </li>
        )}

        {pending.map((item, index) => (
          <li
            key={item.run_id}
            className="glass-control flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5"
          >
            <span className="truncate font-mono text-sm text-muted-foreground">
              <span className="mr-1.5 text-[0.62rem] text-muted-foreground/70">
                {index + 1}
              </span>
              {item.ticker}
            </span>
            <span className="flex items-center gap-0.5">
              <button
                type="button"
                onClick={() => move(index, -1)}
                disabled={index === 0}
                aria-label="上移"
                className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30 focus-visible:outline-none focus-visible:border-primary"
              >
                <ChevronUp className="size-3.5" aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={() => move(index, 1)}
                disabled={index === pending.length - 1}
                aria-label="下移"
                className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30 focus-visible:outline-none focus-visible:border-primary"
              >
                <ChevronDown className="size-3.5" aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={() => onRemove(item.run_id)}
                aria-label="移除"
                className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-destructive focus-visible:outline-none focus-visible:border-primary"
              >
                <X className="size-3.5" aria-hidden="true" />
              </button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `cd webui && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: 提交**

```bash
git add webui/components/QueuePanel.tsx
git commit -m "feat(webui): add QueuePanel component"
```

---

## Task 8: ConfigCard 多代码输入 + page.tsx 队列接线

**Files:**
- Modify: `webui/components/ConfigCard.tsx`
- Modify: `webui/app/page.tsx`

**Interfaces:**
- Consumes: `enqueueAnalysis` / `getQueue` / `removeQueueItem` / `clearQueue` / `reorderQueue`（Task 6），`QueuePanel`（Task 7），`QueueState`（types）。
- Produces: ConfigCard 的 `onStart` 改为传 `tickers: string[]`；page 维护 `queue` state，SSE 跟随当前 running。

- [ ] **Step 1: 先读 Next 文档约束**

Run: `ls "webui/node_modules/next/dist/docs/"`
说明：本任务改客户端组件（`"use client"`），确认 `useState`/`useEffect`/事件处理无破坏性变更后再写。

- [ ] **Step 2: 改 ConfigCard — 多代码输入**

`webui/components/ConfigCard.tsx`：

把 props 的 `onStart` 类型与第 15 行 state 改为多代码。第 6-15 行改为：

```tsx
export function ConfigCard({
  options,
  onStart,
  running = false,
}: {
  options: ConfigOptions;
  onStart: (req: { tickers: string[] } & Omit<AnalysisRequest, "ticker">) => void;
  running?: boolean;
}) {
  const [tickersText, setTickersText] = useState("NVDA");
```

新增解析函数（在 `activeAnalysts` 定义之前加）：

```tsx
  const parsedTickers = Array.from(
    new Set(
      tickersText
        .split(/[\s,，、\n]+/)
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean),
    ),
  );
```

`onSubmit`（第 68-81 行）改为传 `tickers`：

```tsx
      onSubmit={(e) => {
        e.preventDefault();
        onStart({
          tickers: parsedTickers,
          trade_date: date,
          asset_type: assetType,
          analysts: activeAnalysts,
          research_depth: depth,
          output_language: language,
          llm_provider: null,
          deep_think_llm: deepLlm || null,
          quick_think_llm: quickLlm || null,
        });
      }}
```

ticker 输入框（第 171-179 行的 `<input>`）改为 `<textarea>` 支持多行：

```tsx
            <label className="space-y-1">
              <span className="sr-only">Tickers</span>
              <textarea
                rows={2}
                className="glass-control w-full resize-y rounded-md px-2.5 py-1.5 font-mono text-sm tracking-wide text-foreground placeholder:text-muted-foreground outline-none transition-colors focus:border-primary"
                value={tickersText}
                onChange={(e) => setTickersText(e.target.value)}
                placeholder="NVDA, AAPL, 159241.SZ"
              />
            </label>
```

提交按钮（第 280-295 行）：禁用条件与文案随数量变化。`disabled` 改为：

```tsx
          disabled={running || activeAnalysts.length === 0 || parsedTickers.length === 0}
```

按钮文案（第 294 行 `{running ? "分析进行中" : "开始分析"}`）改为：

```tsx
          {running
            ? "分析进行中"
            : parsedTickers.length > 1
              ? `分析 ${parsedTickers.length} 个标的`
              : "开始分析"}
```

- [ ] **Step 3: 类型检查 ConfigCard 改动**

Run: `cd webui && npx tsc --noEmit`
Expected: 报 `page.tsx` 调用 `onStart` 处类型不匹配（预期，下一步修）。ConfigCard 自身无错。

- [ ] **Step 4: 改 page.tsx — 队列 state、入队、SSE 跟随**

`webui/app/page.tsx`：

import（第 12-21 行）加入队列 helper 与 QueuePanel、QueueState：

```tsx
import { QueuePanel } from "@/components/QueuePanel";
import {
  deleteHistory,
  getConfigOptions,
  getHistory,
  getHistoryDetail,
  getAnalysisStatus,
  cancelAnalysis,
  enqueueAnalysis,
  getQueue,
  removeQueueItem,
  clearQueue,
  reorderQueue,
} from "@/lib/api";
```

types import（第 22-29 行）加入 `QueueState`：

```tsx
import type {
  ConfigOptions,
  Decision,
  HistorySummary,
  QueueState,
  RunResult,
  RunStatusDetail,
  SSEEvent,
} from "@/lib/types";
```

新增 queue state（在 `unsubscribeRef` 第 107 行之后）：

```tsx
  const [queue, setQueue] = useState<QueueState>({ running: null, pending: [] });

  const refreshQueue = () =>
    getQueue()
      .then(setQueue)
      .catch(() => setQueue({ running: null, pending: [] }));
```

初始 effect（第 127-131 行）追加 `refreshQueue()`：

```tsx
  useEffect(() => {
    getConfigOptions().then(setOptions).catch(() => setError("无法连接后端"));
    refreshHistory();
    refreshQueue();
    return () => unsubscribeRef.current?.();
  }, []);
```

新增「订阅某个 run 并在结束后跟随队列下一个」的函数，替换原 `onStart`（第 222-269 行）。新代码：

```tsx
  const resetRunView = () => {
    setStatuses({});
    setMessages([]);
    setDecision(null);
    setLiveRuntimeStatus(null);
    setLiveRuntimeError(null);
    setCanceling(false);
  };

  const followRun = (runId: string) => {
    setCurrentRunId(runId);
    setRunning(true);
    unsubscribeRef.current = subscribe(
      runId,
      (e: SSEEvent) => {
        if (e.event === "agent_status")
          setStatuses((s) => ({ ...s, [e.data.agent]: e.data.status }));
        else if (e.event === "message")
          setMessages((m) => [...m, { agent: e.data.agent, content: e.data.content }]);
        else if (e.event === "done")
          setDecision({ d: e.data.decision, detail: e.data.final_trade_decision });
        else if (e.event === "error") setError(e.data.message);
        else if (e.event === "cancelled") setError("分析已停止");
      },
      () => {
        unsubscribeRef.current = null;
        refreshHistory();
        // follow the next running item, if the scheduler advanced
        getQueue()
          .then((q) => {
            setQueue(q);
            if (q.running) {
              resetRunView();
              followRun(q.running.run_id);
            } else {
              setRunning(false);
              setCanceling(false);
              setCurrentRunId(null);
              setError((current) => (current === BUSY_ERROR ? null : current));
            }
          })
          .catch(() => {
            setRunning(false);
            setCurrentRunId(null);
          });
      },
    );
  };

  const onStart = async (req: Parameters<typeof enqueueAnalysis>[0]) => {
    exitDetail();
    resetRunView();
    setError(null);
    try {
      const { running_run_id, queue: nextQueue } = await enqueueAnalysis(req);
      setQueue(nextQueue);
      refreshHistory();
      if (running_run_id) followRun(running_run_id);
    } catch (err) {
      setRunning(false);
      setCurrentRunId(null);
      setError((err as Error).message);
    }
  };
```

队列管理回调（在 `onCancel` 第 299-302 行之后新增）：

```tsx
  const onRemoveQueueItem = (runId: string) =>
    removeQueueItem(runId).then(refreshQueue).catch((e) => setError((e as Error).message));

  const onClearQueue = () =>
    clearQueue().then(refreshQueue).catch((e) => setError((e as Error).message));

  const onReorderQueue = (orderedRunIds: string[]) =>
    reorderQueue(orderedRunIds).then(setQueue).catch((e) => setError((e as Error).message));
```

`cancelRun`（第 271-297 行）末尾在 `refreshHistory();` 旁补 `refreshQueue();`（取消后队列要刷新；推进由后端做，前端靠 SSE onClose 跟随）。在第 281 行 `refreshHistory();` 后加：

```tsx
      refreshQueue();
```

在 aside 渲染处，把 `<AgentProgress .../>`（第 528 行）之前插入 QueuePanel：

```tsx
            <QueuePanel
              queue={queue}
              onRemove={onRemoveQueueItem}
              onClear={onClearQueue}
              onReorder={onReorderQueue}
              onCancelRunning={(runId) => void cancelRun(runId)}
              canceling={canceling}
            />

            <AgentProgress statuses={sidebarStatuses} />
```

- [ ] **Step 5: 类型检查全绿**

Run: `cd webui && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 6: 提交**

```bash
git add webui/components/ConfigCard.tsx webui/app/page.tsx
git commit -m "feat(webui): multi-ticker input and queue-following UI"
```

- [ ] **Step 7: 手动验证（dev 服务）**

Run: `./dev.sh`（或分别启动 API 与 `cd webui && npm run dev`）
逐项确认：
1. ticker 框输入 `NVDA, AAPL, TSLA` → 点「分析 3 个标的」→ 第一个开始跑、队列里出现 AAPL/TSLA。
2. 第一个跑完 → 自动跟随 AAPL，TSLA 仍排队。
3. 对 TSLA 点「上移/下移/移除」、点「清空」生效。
4. 对运行中项点停止 → 标 cancelled → 自动跟到下一个。
5. 刷新页面 → 队列（pending）仍在。
6. 制造一个会失败的代码（如非法 ticker）→ 该项 error → 队列继续下一个。

---

## Task 9: 文档（CHANGELOG + AGENTS.md）

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`（WebUI 段落补充队列说明）

- [ ] **Step 1: 更新 CHANGELOG**

`CHANGELOG.md` 的 `## [Unreleased]`（或最新未发布段）`### Added` 下追加：

```markdown
- **WebUI 分析队列**：一次输入多个标的代码，持久化为后端队列，由调度器串行依次分析；
  支持移除/清空/重排 pending、取消当前并自动推进、出错跳过；服务重启后 pending 队列保留。
```

- [ ] **Step 2: 更新 AGENTS.md**

在 `AGENTS.md` 的 `## WebUI (api/ + webui/)` 段落中，`单用户不变量：一次只能跑一个 run（409 if busy）` 一句后补充：

```markdown
  现已引入**队列**：`POST /api/queue` 批量入队（`status='pending'`），`api/scheduler.py::QueueScheduler`
  串行启动下一个 pending（runner 线程结束后回调 `advance()`），出错/取消自动跳过推进；
  `POST /api/analysis` 改为「入队单个 + 调度」，忙时不再 409 而是排队。启动时 `reset_orphaned_runs()`
  复位残留 running 行。队列接口见 `api/routes/queue.py`。
```

- [ ] **Step 3: 收尾全量验证**

Run: `.venv/bin/python -m ruff check . && .venv/bin/python -m pytest -m "not integration" -q`
Expected: ruff 0 error；pytest 全绿

- [ ] **Step 4: 提交**

```bash
git add CHANGELOG.md AGENTS.md
git commit -m "docs(webui): document analysis queue feature"
```

---

## Self-Review

**Spec coverage（对照设计文档逐节）：**
- §3 方案 C 调度器 → Task 3 + Task 4（main 接线、runner finally 推进）。✓
- §4 数据模型（加列、pending、重启复位）→ Task 1 + Task 2。✓
- §5 Store 全部方法 → Task 2。✓
- §6 Scheduler `advance`/`_start`/启动恢复 → Task 3 + Task 4。✓
- §7 API 5 接口 + `POST /api/analysis` 改造 + cancel 不直接 advance → Task 4 + Task 5。✓
- §8 前端（多代码输入、QueuePanel、page 轮询+SSE 跟随）→ Task 6/7/8。✓
- §9 测试（store 单测、调度推进、出错跳过、取消推进、接口、重启恢复、迁移、smoke）→ 散落 Task 2/3/4/5；前端手动验证 Task 8 Step 7。✓
- §10 兼容（迁移、`POST /api/analysis` 兼容、history 排除 pending）→ Task 2（list_runs 过滤）+ Task 4。✓

**Placeholder scan：** Task 5 Step 1 的 `_install_gated_graph` 第一版含占位误写，已在同步骤给出「干净版」并注明实现时用干净版替换——非遗留 TODO。其余无 TBD/TODO。✓

**Type consistency：**
- `enqueue_run / start_run / next_pending / list_queue / remove_pending / clear_pending / reorder_pending / reset_orphaned_runs` 在 Task 2 定义，Task 3/4/5 调用名一致。✓
- `QueueScheduler.advance()` 名称在 Task 3/4/5 一致。✓
- 前端 `enqueueAnalysis / getQueue / removeQueueItem / clearQueue / reorderQueue` 在 Task 6 定义，Task 8 调用一致。✓
- `QueuePanel` props（`onRemove/onClear/onReorder/onCancelRunning/canceling/queue`）Task 7 定义，Task 8 传参一致。✓
- ConfigCard `onStart` 签名从 `AnalysisRequest` 改为 `{tickers} & Omit<AnalysisRequest,"ticker">`，page `onStart`/`enqueueAnalysis` 入参一致。✓
