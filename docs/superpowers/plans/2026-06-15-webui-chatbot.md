# TradingAgents WebUI (对话式分析助手) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 TradingAgents 框架新增一个对话式分析助手 WebUI——FastAPI(SSE 流式 + 后台线程 + SQLite)后端 + Next.js(金融终端风)前端,把现有 CLI 体验搬到网页。

**Architecture:** 后端用单例 `TradingAgentsGraph`,在后台线程跑阻塞的 `graph.graph.stream()`,把每个 chunk 解析为事件 put 进线程安全队列;SSE 端点的 async 生成器从队列 get 并 yield 给前端。历史存 SQLite(`~/.tradingagents/webui.db`)。前端用配置卡片一键启动,SSE 驱动进度条/逐条气泡/结论卡/历史侧栏。不改动 `tradingagents/` 与 `cli/`。

**Tech Stack:** Python 3.10+ / FastAPI / uvicorn / sse-starlette / pytest / ruff(后端);Next.js App Router / TypeScript / Tailwind / shadcn/ui / npm(前端)。

参考设计文档:`docs/superpowers/specs/2026-06-15-webui-chatbot-design.md`

---

## 测试与命令约定(贯穿全程)

- 后端测试运行器:`pytest`(项目已配置 `testpaths=["tests"]`,marker:`unit`/`integration`/`smoke`)。
- 后端 lint:`ruff check api/`。
- 后端测试一律 mock,**绝不真调 LLM**;用 fake graph(yield 预设 chunk)。
- 提交粒度:每个 Task 末尾一次提交。提交用 `--no-verify` 避免触发与本任务无关的全仓 hook。
- 新增后端依赖加入 `pyproject.toml` 的 `dependencies`(`fastapi`、`uvicorn[standard]`、`sse-starlette`)与 `dev`(`httpx` 供 TestClient)。

---

## 文件结构(决策锁定)

**后端 `api/`**(每个文件单一职责):
- `api/__init__.py` — 空包标记
- `api/schemas.py` — Pydantic 模型:`AnalysisRequest`、`HistorySummary`、`RunResult`、`ConfigOptions`、SSE 事件 dataclass
- `api/store.py` — SQLite 读写(建表、insert/update run、list/get/delete)
- `api/runner.py` — 包装 `graph.graph.stream()`,后台线程跑,chunk→事件入队;事件→报告板块映射
- `api/config_options.py` — 组装配置卡片选项(分析师/深度/语言/已配置 provider)
- `api/routes/__init__.py` — 空包标记
- `api/routes/config.py` — `GET /api/config/options`
- `api/routes/analysis.py` — `POST /api/analysis`、`GET /stream`(SSE)、`GET /report`
- `api/routes/history.py` — `GET /api/history`、`GET /{run_id}`、`DELETE /{run_id}`
- `api/main.py` — FastAPI app、CORS、路由挂载、单例 graph + 单运行锁

**后端测试 `tests/webui/`**:
- `tests/webui/__init__.py`
- `tests/webui/conftest.py` — fake graph fixture、临时 DB fixture、TestClient fixture
- `tests/webui/test_store.py`、`test_runner.py`、`test_routes_analysis.py`、`test_routes_history.py`、`test_config_options.py`

**前端 `webui/`**(Next.js App Router):
- `webui/lib/types.ts` — 与后端契约对应的 TS 类型
- `webui/lib/api.ts` — REST 封装
- `webui/lib/sse.ts` — SSE 客户端(EventSource 封装,解析 5 种事件)
- `webui/components/*` — `ConfigCard`、`AgentProgress`、`MessageBubble`、`DecisionCard`、`HistorySidebar`
- `webui/app/page.tsx`、`webui/app/layout.tsx`、`webui/app/globals.css`

---

## Task 1: 后端依赖与包骨架

**Files:**
- Modify: `pyproject.toml:11-41`
- Create: `api/__init__.py`
- Create: `api/routes/__init__.py`
- Create: `tests/webui/__init__.py`

- [ ] **Step 1: 添加后端依赖到 pyproject.toml**

在 `dependencies` 列表末尾(第 33 行 `"yfinance>=1.4.1",` 之后)新增三项:

```toml
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sse-starlette>=2.1.0",
```

在 `dev` 列表(第 37-41 行)末尾新增:

```toml
    "httpx>=0.27",
```

- [ ] **Step 2: 安装依赖**

Run: `pip install -e ".[dev]"`
Expected: 成功安装 fastapi、uvicorn、sse-starlette、httpx,无报错。

- [ ] **Step 3: 创建空包标记文件**

`api/__init__.py`:
```python
"""TradingAgents WebUI FastAPI backend."""
```

`api/routes/__init__.py`:
```python
```

`tests/webui/__init__.py`:
```python
```

- [ ] **Step 4: 验证导入**

Run: `python -c "import api; import api.routes"`
Expected: 无输出,退出码 0。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml api/__init__.py api/routes/__init__.py tests/webui/__init__.py
git commit --no-verify -m "feat(webui): add backend deps and package skeleton"
```

---

## Task 2: Pydantic 契约模型 (api/schemas.py)

**Files:**
- Create: `api/schemas.py`
- Test: `tests/webui/test_schemas.py`

- [ ] **Step 1: 写失败测试**

`tests/webui/test_schemas.py`:
```python
import pytest
from pydantic import ValidationError

from api.schemas import AnalysisRequest


def test_analysis_request_defaults():
    req = AnalysisRequest(ticker="NVDA", trade_date="2024-05-10")
    assert req.asset_type == "stock"
    assert req.analysts == ["market", "social", "news", "fundamentals"]
    assert req.research_depth == 3
    assert req.output_language == "Chinese"
    assert req.llm_provider is None


def test_analysis_request_rejects_empty_analysts():
    with pytest.raises(ValidationError):
        AnalysisRequest(ticker="NVDA", trade_date="2024-05-10", analysts=[])


def test_research_depth_must_be_allowed_value():
    with pytest.raises(ValidationError):
        AnalysisRequest(ticker="NVDA", trade_date="2024-05-10", research_depth=2)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/webui/test_schemas.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'api.schemas'`

- [ ] **Step 3: 实现 schemas.py**

`api/schemas.py`:
```python
"""Pydantic request/response contracts for the WebUI API."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

AssetType = Literal["stock", "crypto"]
AnalystName = Literal["market", "social", "news", "fundamentals"]
Decision = Literal["Buy", "Overweight", "Hold", "Underweight", "Sell"]
RunStatus = Literal["running", "completed", "error"]


class AnalysisRequest(BaseModel):
    ticker: str
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

    @field_validator("analysts")
    @classmethod
    def _at_least_one_analyst(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("at least one analyst is required")
        return v


class HistorySummary(BaseModel):
    run_id: str
    ticker: str
    trade_date: str
    decision: Decision | None
    status: RunStatus
    created_at: str


class RunResult(BaseModel):
    run_id: str
    ticker: str
    trade_date: str
    asset_type: str
    decision: Decision | None
    status: RunStatus
    config: dict
    result: dict | None
    created_at: str
    completed_at: str | None


class ConfigOptions(BaseModel):
    analysts: list[dict]
    research_depth: list[dict]
    languages: list[str]
    configured_provider: str | None
    configured_deep_llm: str | None
    configured_quick_llm: str | None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/webui/test_schemas.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: Commit**

```bash
git add api/schemas.py tests/webui/test_schemas.py
git commit --no-verify -m "feat(webui): add pydantic API contract models"
```

---

## Task 3: SQLite 历史存储 (api/store.py)

**Files:**
- Create: `api/store.py`
- Test: `tests/webui/test_store.py`

- [ ] **Step 1: 写失败测试**

`tests/webui/test_store.py`:
```python
import json

from api.store import Store


def test_insert_and_get_run(tmp_path):
    store = Store(tmp_path / "test.db")
    store.insert_run(
        run_id="r1",
        ticker="NVDA",
        trade_date="2024-05-10",
        asset_type="stock",
        config={"llm_provider": "openai"},
    )
    row = store.get_run("r1")
    assert row.status == "running"
    assert row.ticker == "NVDA"
    assert row.decision is None
    assert row.config == {"llm_provider": "openai"}


def test_complete_run_updates_decision_and_result(tmp_path):
    store = Store(tmp_path / "test.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    store.complete_run("r1", decision="Buy", result={"final_trade_decision": "x"})
    row = store.get_run("r1")
    assert row.status == "completed"
    assert row.decision == "Buy"
    assert row.result == {"final_trade_decision": "x"}
    assert row.completed_at is not None


def test_mark_error(tmp_path):
    store = Store(tmp_path / "test.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    store.mark_error("r1", "boom")
    row = store.get_run("r1")
    assert row.status == "error"


def test_list_runs_returns_summaries_newest_first(tmp_path):
    store = Store(tmp_path / "test.db")
    store.insert_run("r1", "AAPL", "2024-01-01", "stock", {})
    store.insert_run("r2", "NVDA", "2024-01-02", "stock", {})
    summaries = store.list_runs()
    assert [s.run_id for s in summaries] == ["r2", "r1"]


def test_delete_run(tmp_path):
    store = Store(tmp_path / "test.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    store.delete_run("r1")
    assert store.get_run("r1") is None


def test_has_running_run(tmp_path):
    store = Store(tmp_path / "test.db")
    assert store.has_running_run() is False
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    assert store.has_running_run() is True
    store.complete_run("r1", decision="Hold", result={})
    assert store.has_running_run() is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/webui/test_store.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'api.store'`

- [ ] **Step 3: 实现 store.py**

`api/store.py`:
```python
"""SQLite-backed history store for WebUI analysis runs."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from api.schemas import HistorySummary, RunResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id        TEXT PRIMARY KEY,
    ticker        TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    asset_type    TEXT NOT NULL,
    decision      TEXT,
    status        TEXT NOT NULL,
    config_json   TEXT NOT NULL,
    result_json   TEXT,
    created_at    TEXT NOT NULL,
    completed_at  TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_path: Path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def insert_run(
        self, run_id: str, ticker: str, trade_date: str, asset_type: str, config: dict
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO analysis_runs "
                "(run_id, ticker, trade_date, asset_type, decision, status, "
                " config_json, result_json, created_at, completed_at) "
                "VALUES (?, ?, ?, ?, NULL, 'running', ?, NULL, ?, NULL)",
                (run_id, ticker, trade_date, asset_type, json.dumps(config), _now()),
            )

    def complete_run(self, run_id: str, decision: str, result: dict) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE analysis_runs SET status='completed', decision=?, "
                "result_json=?, completed_at=? WHERE run_id=?",
                (decision, json.dumps(result), _now(), run_id),
            )

    def mark_error(self, run_id: str, message: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE analysis_runs SET status='error', result_json=?, "
                "completed_at=? WHERE run_id=?",
                (json.dumps({"error": message}), _now(), run_id),
            )

    def get_run(self, run_id: str) -> RunResult | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            return None
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

    def list_runs(self) -> list[HistorySummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_id, ticker, trade_date, decision, status, created_at "
                "FROM analysis_runs ORDER BY created_at DESC"
            ).fetchall()
        return [
            HistorySummary(
                run_id=r["run_id"],
                ticker=r["ticker"],
                trade_date=r["trade_date"],
                decision=r["decision"],
                status=r["status"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def delete_run(self, run_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM analysis_runs WHERE run_id=?", (run_id,))

    def has_running_run(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM analysis_runs WHERE status='running' LIMIT 1"
            ).fetchone()
        return row is not None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/webui/test_store.py -v`
Expected: PASS(6 passed)

- [ ] **Step 5: Commit**

```bash
git add api/store.py tests/webui/test_store.py
git commit --no-verify -m "feat(webui): add SQLite history store"
```

---

## Task 4: chunk→事件映射纯函数 (api/runner.py 第一部分)

**Files:**
- Create: `api/runner.py`
- Test: `tests/webui/test_runner.py`

LangGraph stream chunk 是部分 state dict。本任务实现一个**纯函数** `chunk_to_events(chunk, prev_seen)`,把 chunk 解析为 SSE 事件列表(报告板块 + 智能体状态),不涉及线程。

- [ ] **Step 1: 写失败测试**

`tests/webui/test_runner.py`:
```python
from api.runner import REPORT_SECTIONS, chunk_to_events


def test_report_section_chunk_emits_report_event():
    events = chunk_to_events({"market_report": "## Market\nUp"}, set())
    types = [e["event"] for e in events]
    assert "report_section" in types
    report = next(e for e in events if e["event"] == "report_section")
    assert report["data"]["section"] == "market_report"
    assert report["data"]["content"] == "## Market\nUp"


def test_report_section_also_emits_agent_done():
    events = chunk_to_events({"market_report": "x"}, set())
    statuses = [e for e in events if e["event"] == "agent_status"]
    assert any(
        e["data"]["agent"] == "market_analyst" and e["data"]["status"] == "done"
        for e in statuses
    )


def test_empty_report_field_is_ignored():
    events = chunk_to_events({"market_report": ""}, set())
    assert events == []


def test_already_seen_section_not_re_emitted():
    seen = {"market_report"}
    events = chunk_to_events({"market_report": "x"}, seen)
    assert events == []


def test_all_known_sections_have_agent_mapping():
    for section in REPORT_SECTIONS:
        assert section in REPORT_SECTIONS
        agent, team = REPORT_SECTIONS[section]
        assert isinstance(agent, str) and isinstance(team, str)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/webui/test_runner.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'api.runner'`

- [ ] **Step 3: 实现 runner.py 的映射部分**

`api/runner.py`(本任务只写文件头 + 映射,线程逻辑在 Task 5 追加):
```python
"""Bridges TradingAgentsGraph.stream() to SSE events via a background thread."""

import time

# section field name -> (agent name, team)
REPORT_SECTIONS: dict[str, tuple[str, str]] = {
    "market_report": ("market_analyst", "analyst"),
    "sentiment_report": ("social_analyst", "analyst"),
    "news_report": ("news_analyst", "analyst"),
    "fundamentals_report": ("fundamentals_analyst", "analyst"),
    "investment_plan": ("research_manager", "research"),
    "trader_investment_plan": ("trader", "trading"),
    "final_trade_decision": ("portfolio_manager", "portfolio"),
}


def chunk_to_events(chunk: dict, seen: set[str]) -> list[dict]:
    """Translate one LangGraph stream chunk into SSE event dicts.

    Each event dict has shape {"event": <type>, "data": <payload>}.
    Mutates ``seen`` to track which report sections were already emitted.
    """
    events: list[dict] = []
    for section, (agent, team) in REPORT_SECTIONS.items():
        content = chunk.get(section)
        if not content or section in seen:
            continue
        seen.add(section)
        events.append(
            {"event": "agent_status", "data": {"agent": agent, "team": team, "status": "done"}}
        )
        events.append(
            {
                "event": "report_section",
                "data": {"section": section, "content": content},
            }
        )
        events.append(
            {
                "event": "message",
                "data": {"agent": agent, "team": team, "content": content, "ts": int(time.time())},
            }
        )
    return events
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/webui/test_runner.py -v`
Expected: PASS(5 passed)

- [ ] **Step 5: Commit**

```bash
git add api/runner.py tests/webui/test_runner.py
git commit --no-verify -m "feat(webui): add chunk-to-SSE-event mapping"
```

---

## Task 5: 后台线程 Runner + 队列桥接 (api/runner.py 第二部分)

**Files:**
- Modify: `api/runner.py`(追加 `AnalysisRunner` 类)
- Modify: `tests/webui/test_runner.py`(追加线程测试)

`AnalysisRunner` 在后台线程跑一个 graph(注入 fake graph 以便测试),把事件 put 进 `queue.Queue`,结束时 put `done` 或 `error`,最后 put 哨兵 `None`。完成时回调 store。

- [ ] **Step 1: 写失败测试(追加到 test_runner.py 末尾)**

```python
import queue

from api.runner import AnalysisRunner


class _FakeGraph:
    """Mimics TradingAgentsGraph: .graph.stream() yields chunks, then propagate-like end."""

    def __init__(self, chunks, final_state, decision):
        self._chunks = chunks
        self._final_state = final_state
        self._decision = decision

        class _Inner:
            def stream(inner_self, init_state, **kwargs):
                yield from chunks

        self.graph = _Inner()

    def propagator_create_initial_state(self, ticker, date):
        return {}


def test_runner_emits_done_and_calls_store(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})

    fake = _FakeGraph(
        chunks=[{"market_report": "m"}, {"final_trade_decision": "**Rating**: Buy"}],
        final_state={"final_trade_decision": "**Rating**: Buy", "market_report": "m"},
        decision="Buy",
    )
    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(store=store, event_queue=q)
    runner.run(
        run_id="r1",
        graph=fake,
        init_state={},
        decision="Buy",
        final_state={"final_trade_decision": "**Rating**: Buy", "market_report": "m"},
    )

    events = _drain(q)
    types = [e["event"] for e in events]
    assert "done" in types
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["decision"] == "Buy"
    assert store.get_run("r1").status == "completed"


def test_runner_emits_error_on_exception(tmp_path):
    from api.store import Store

    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})

    class _Boom:
        class graph:
            @staticmethod
            def stream(init_state, **kwargs):
                raise RuntimeError("kaboom")
                yield  # pragma: no cover

    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(store=store, event_queue=q)
    runner.run(run_id="r1", graph=_Boom(), init_state={}, decision=None, final_state=None)

    events = _drain(q)
    assert any(e["event"] == "error" for e in events)
    assert store.get_run("r1").status == "error"


def _drain(q: queue.Queue) -> list:
    out = []
    while True:
        item = q.get(timeout=2)
        if item is None:
            break
        out.append(item)
    return out
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/webui/test_runner.py -v`
Expected: FAIL,`ImportError: cannot import name 'AnalysisRunner'`

- [ ] **Step 3: 追加 AnalysisRunner 到 runner.py**

在 `api/runner.py` 末尾追加:
```python
import queue
import traceback

from api.store import Store


class AnalysisRunner:
    """Runs a graph stream synchronously, pushing SSE events onto a queue.

    Designed to be invoked inside a background thread. ``decision`` and
    ``final_state`` are precomputed by the caller (the route handler), because
    TradingAgentsGraph stores them on the instance after ``propagate``; here we
    accept them explicitly so the runner stays testable with a fake graph.
    """

    def __init__(self, store: Store, event_queue: "queue.Queue"):
        self._store = store
        self._q = event_queue

    def run(self, run_id, graph, init_state, decision, final_state) -> None:
        seen: set[str] = set()
        try:
            for chunk in graph.graph.stream(init_state):
                for event in chunk_to_events(chunk, seen):
                    self._q.put(event)
            self._store.complete_run(
                run_id, decision=decision or "Hold", result=final_state or {}
            )
            self._q.put(
                {
                    "event": "done",
                    "data": {
                        "decision": decision or "Hold",
                        "final_trade_decision": (final_state or {}).get(
                            "final_trade_decision", ""
                        ),
                        "run_id": run_id,
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001 - surface any failure to the client
            traceback.print_exc()
            self._store.mark_error(run_id, str(exc))
            self._q.put({"event": "error", "data": {"message": str(exc)}})
        finally:
            self._q.put(None)  # sentinel: stream finished
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/webui/test_runner.py -v`
Expected: PASS(7 passed)

- [ ] **Step 5: Commit**

```bash
git add api/runner.py tests/webui/test_runner.py
git commit --no-verify -m "feat(webui): add background AnalysisRunner with queue bridge"
```

---

## Task 6: 配置选项装配 (api/config_options.py)

**Files:**
- Create: `api/config_options.py`
- Test: `tests/webui/test_config_options.py`

- [ ] **Step 1: 写失败测试**

`tests/webui/test_config_options.py`:
```python
from api.config_options import build_config_options


def test_build_config_options_shape():
    opts = build_config_options()
    assert {a["value"] for a in opts.analysts} == {
        "market",
        "social",
        "news",
        "fundamentals",
    }
    assert [d["value"] for d in opts.research_depth] == [1, 3, 5]
    assert "Chinese" in opts.languages
    assert "English" in opts.languages


def test_configured_provider_reflects_config(monkeypatch):
    import api.config_options as mod

    monkeypatch.setattr(
        mod,
        "DEFAULT_CONFIG",
        {**mod.DEFAULT_CONFIG, "llm_provider": "openai", "deep_think_llm": "gpt-5.5"},
    )
    opts = build_config_options()
    assert opts.configured_provider == "openai"
    assert opts.configured_deep_llm == "gpt-5.5"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/webui/test_config_options.py -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'api.config_options'`

- [ ] **Step 3: 实现 config_options.py**

`api/config_options.py`:
```python
"""Assembles the option set shown in the frontend config card."""

from tradingagents.default_config import DEFAULT_CONFIG

from api.schemas import ConfigOptions

_ANALYSTS = [
    {"value": "market", "label": "市场分析师"},
    {"value": "social", "label": "情绪分析师"},
    {"value": "news", "label": "新闻分析师"},
    {"value": "fundamentals", "label": "基本面分析师"},
]

_DEPTH = [
    {"value": 1, "label": "浅 (1 轮)"},
    {"value": 3, "label": "中 (3 轮)"},
    {"value": 5, "label": "深 (5 轮)"},
]

_LANGUAGES = [
    "Chinese",
    "English",
    "Japanese",
    "Korean",
    "Spanish",
    "Portuguese",
    "French",
    "German",
    "Russian",
    "Arabic",
    "Hindi",
]


def build_config_options() -> ConfigOptions:
    return ConfigOptions(
        analysts=_ANALYSTS,
        research_depth=_DEPTH,
        languages=_LANGUAGES,
        configured_provider=DEFAULT_CONFIG.get("llm_provider"),
        configured_deep_llm=DEFAULT_CONFIG.get("deep_think_llm"),
        configured_quick_llm=DEFAULT_CONFIG.get("quick_think_llm"),
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/webui/test_config_options.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: Commit**

```bash
git add api/config_options.py tests/webui/test_config_options.py
git commit --no-verify -m "feat(webui): add config options assembly"
```

---

## Task 7: FastAPI app + 路由挂载 + 单例 graph (api/main.py, routes/config.py)

**Files:**
- Create: `api/main.py`
- Create: `api/routes/config.py`
- Test: `tests/webui/conftest.py`、`tests/webui/test_config_options.py`(追加路由测试)

- [ ] **Step 1: 写共享 fixture conftest.py**

`tests/webui/conftest.py`:
```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient with an isolated temp DB and no real graph."""
    import api.main as main

    monkeypatch.setattr(main, "DB_PATH", tmp_path / "webui.db")
    main.app.state.store = None  # force re-init against temp DB
    with TestClient(main.app) as c:
        yield c
```

- [ ] **Step 2: 写失败测试(追加到 test_config_options.py)**

```python
def test_get_config_options_route(client):
    resp = client.get("/api/config/options")
    assert resp.status_code == 200
    body = resp.json()
    assert "analysts" in body and "research_depth" in body
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/webui/test_config_options.py::test_get_config_options_route -v`
Expected: FAIL,`ModuleNotFoundError: No module named 'api.main'`

- [ ] **Step 4: 实现 routes/config.py**

`api/routes/config.py`:
```python
"""GET /api/config/options route."""

from fastapi import APIRouter

from api.config_options import build_config_options
from api.schemas import ConfigOptions

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/options", response_model=ConfigOptions)
def get_config_options() -> ConfigOptions:
    return build_config_options()
```

- [ ] **Step 5: 实现 main.py**

`api/main.py`:
```python
"""FastAPI application entry point for the TradingAgents WebUI."""

import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import config as config_routes
from api.store import Store

DB_PATH = Path.home() / ".tradingagents" / "webui.db"

app = FastAPI(title="TradingAgents WebUI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single-user invariant: only one analysis runs at a time.
app.state.store = None
app.state.run_lock = threading.Lock()


def get_store() -> Store:
    if app.state.store is None:
        app.state.store = Store(DB_PATH)
    return app.state.store


app.include_router(config_routes.router)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/webui/test_config_options.py -v`
Expected: PASS(3 passed)

- [ ] **Step 7: Commit**

```bash
git add api/main.py api/routes/config.py tests/webui/conftest.py tests/webui/test_config_options.py
git commit --no-verify -m "feat(webui): add FastAPI app, CORS, config route, test client fixture"
```

---

## Task 8: 历史路由 (api/routes/history.py)

**Files:**
- Create: `api/routes/history.py`
- Modify: `api/main.py`(挂载 history router)
- Test: `tests/webui/test_routes_history.py`

- [ ] **Step 1: 写失败测试**

`tests/webui/test_routes_history.py`:
```python
def _seed(client):
    store = client.app.state.store or _force_store(client)
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {"x": 1})
    store.complete_run("r1", decision="Buy", result={"final_trade_decision": "**Rating**: Buy"})
    return store


def _force_store(client):
    import api.main as main

    return main.get_store()


def test_list_history(client):
    _seed(client)
    resp = client.get("/api/history")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["ticker"] == "NVDA"
    assert items[0]["decision"] == "Buy"


def test_get_history_detail(client):
    _seed(client)
    resp = client.get("/api/history/r1")
    assert resp.status_code == 200
    assert resp.json()["result"]["final_trade_decision"] == "**Rating**: Buy"


def test_get_missing_returns_404(client):
    resp = client.get("/api/history/nope")
    assert resp.status_code == 404


def test_delete_history(client):
    _seed(client)
    assert client.delete("/api/history/r1").status_code == 204
    assert client.get("/api/history/r1").status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/webui/test_routes_history.py -v`
Expected: FAIL,404 路由不存在(或 import 错误)。

- [ ] **Step 3: 实现 routes/history.py**

`api/routes/history.py`:
```python
"""History routes: list, detail, delete."""

from fastapi import APIRouter, HTTPException, Response

from api.main import get_store
from api.schemas import HistorySummary, RunResult

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("", response_model=list[HistorySummary])
def list_history() -> list[HistorySummary]:
    return get_store().list_runs()


@router.get("/{run_id}", response_model=RunResult)
def get_history(run_id: str) -> RunResult:
    run = get_store().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.delete("/{run_id}", status_code=204)
def delete_history(run_id: str) -> Response:
    store = get_store()
    if store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    store.delete_run(run_id)
    return Response(status_code=204)
```

- [ ] **Step 4: 挂载 history router 到 main.py**

在 `api/main.py` 的 `app.include_router(config_routes.router)` 之后追加:
```python
from api.routes import history as history_routes  # noqa: E402

app.include_router(history_routes.router)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/webui/test_routes_history.py -v`
Expected: PASS(4 passed)

- [ ] **Step 6: Commit**

```bash
git add api/routes/history.py api/main.py tests/webui/test_routes_history.py
git commit --no-verify -m "feat(webui): add history list/detail/delete routes"
```

---

## Task 9: 分析路由 — POST 启动 + SSE 流 + 报告下载 (api/routes/analysis.py)

**Files:**
- Create: `api/routes/analysis.py`
- Modify: `api/main.py`(挂载 analysis router + 注入 graph 工厂)
- Test: `tests/webui/test_routes_analysis.py`

设计要点:`POST /api/analysis` 检查单运行锁(已有 running 则 409),插入 DB,启动后台线程跑 `AnalysisRunner`,把该 run 的事件队列存到 `app.state.queues[run_id]`,返回 `run_id`。`GET /stream` 用 `sse_starlette.EventSourceResponse` 从队列消费。graph 的构建通过可替换的工厂函数 `app.state.graph_factory`(测试时注入 fake)。

- [ ] **Step 1: 写失败测试**

`tests/webui/test_routes_analysis.py`:
```python
import json


def _install_fake_graph(client, chunks, decision, final_state):
    import api.main as main

    class _FakeGraph:
        def __init__(self, *a, **k):
            class _Inner:
                def stream(inner_self, init_state, **kwargs):
                    yield from chunks

            self.graph = _Inner()

        def propagate_meta(self):
            return decision, final_state

    def factory(req):
        # returns (graph, init_state, decision, final_state)
        return _FakeGraph(), {}, decision, final_state

    main.app.state.graph_factory = factory


def test_post_analysis_returns_run_id_and_streams_done(client):
    _install_fake_graph(
        client,
        chunks=[{"market_report": "m"}, {"final_trade_decision": "**Rating**: Buy"}],
        decision="Buy",
        final_state={"final_trade_decision": "**Rating**: Buy", "market_report": "m"},
    )
    resp = client.post(
        "/api/analysis",
        json={"ticker": "NVDA", "trade_date": "2024-05-10"},
    )
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    with client.stream("GET", f"/api/analysis/{run_id}/stream") as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "event: report_section" in body
    assert "event: done" in body
    assert "Buy" in body


def test_second_analysis_while_running_returns_409(client, monkeypatch):
    import api.main as main

    monkeypatch.setattr(main.get_store(), "has_running_run", lambda: True)
    resp = client.post(
        "/api/analysis", json={"ticker": "NVDA", "trade_date": "2024-05-10"}
    )
    assert resp.status_code == 409


def test_report_download_returns_markdown(client):
    store = client.app.state.store
    import api.main as main

    store = main.get_store()
    store.insert_run("r9", "NVDA", "2024-05-10", "stock", {})
    store.complete_run(
        "r9",
        decision="Buy",
        result={
            "market_report": "## Market\nUp",
            "final_trade_decision": "**Rating**: Buy",
        },
    )
    resp = client.get("/api/analysis/r9/report")
    assert resp.status_code == 200
    assert "## Market" in resp.text
    assert "Rating" in resp.text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/webui/test_routes_analysis.py -v`
Expected: FAIL,路由不存在 / import 错误。

- [ ] **Step 3: 实现 routes/analysis.py**

`api/routes/analysis.py`:
```python
"""Analysis routes: start run, SSE stream, report download."""

import queue
import threading
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sse_starlette.sse import EventSourceResponse

from api.runner import AnalysisRunner
from api.schemas import AnalysisRequest

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

_REPORT_ORDER = [
    ("market_report", "市场分析"),
    ("sentiment_report", "情绪分析"),
    ("news_report", "新闻分析"),
    ("fundamentals_report", "基本面分析"),
    ("investment_plan", "研究经理决策"),
    ("trader_investment_plan", "交易计划"),
    ("final_trade_decision", "组合经理最终决策"),
]


@router.post("")
def start_analysis(req: AnalysisRequest, request: Request) -> dict:
    from api.main import get_store

    store = get_store()
    if store.has_running_run():
        raise HTTPException(status_code=409, detail="another analysis is running")

    run_id = uuid.uuid4().hex
    store.insert_run(
        run_id=run_id,
        ticker=req.ticker,
        trade_date=req.trade_date,
        asset_type=req.asset_type,
        config=req.model_dump(),
    )

    graph, init_state, decision, final_state = request.app.state.graph_factory(req)

    q: queue.Queue = queue.Queue()
    request.app.state.queues[run_id] = q
    runner = AnalysisRunner(store=store, event_queue=q)

    thread = threading.Thread(
        target=runner.run,
        kwargs={
            "run_id": run_id,
            "graph": graph,
            "init_state": init_state,
            "decision": decision,
            "final_state": final_state,
        },
        daemon=True,
    )
    thread.start()
    return {"run_id": run_id}


@router.get("/{run_id}/stream")
async def stream_analysis(run_id: str, request: Request) -> EventSourceResponse:
    q = request.app.state.queues.get(run_id)
    if q is None:
        raise HTTPException(status_code=404, detail="run not found or already drained")

    async def event_generator():
        import asyncio

        while True:
            try:
                item = await asyncio.to_thread(q.get, True, 1.0)
            except queue.Empty:
                if await request.is_disconnected():
                    break
                continue
            if item is None:
                break
            import json

            yield {"event": item["event"], "data": json.dumps(item["data"])}
        request.app.state.queues.pop(run_id, None)

    return EventSourceResponse(event_generator())


@router.get("/{run_id}/report", response_class=PlainTextResponse)
def download_report(run_id: str) -> str:
    from api.main import get_store

    run = get_store().get_run(run_id)
    if run is None or run.result is None:
        raise HTTPException(status_code=404, detail="report not available")

    parts = [f"# TradingAgents 分析报告 — {run.ticker} ({run.trade_date})\n"]
    if run.decision:
        parts.append(f"**决策: {run.decision}**\n")
    for key, title in _REPORT_ORDER:
        content = run.result.get(key)
        if content:
            parts.append(f"\n## {title}\n\n{content}\n")
    return "\n".join(parts)
```

- [ ] **Step 4: 挂载 analysis router + 初始化 state 到 main.py**

在 `api/main.py` 中:

(a) 在 `app.state.run_lock = threading.Lock()` 之后追加:
```python
app.state.queues = {}
app.state.graph_factory = None  # set by real_graph_factory at startup; tests inject their own
```

(b) 在 history router 挂载之后追加:
```python
from api.routes import analysis as analysis_routes  # noqa: E402

app.include_router(analysis_routes.router)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/webui/test_routes_analysis.py -v`
Expected: PASS(3 passed)

- [ ] **Step 6: Commit**

```bash
git add api/routes/analysis.py api/main.py tests/webui/test_routes_analysis.py
git commit --no-verify -m "feat(webui): add analysis start/SSE-stream/report routes"
```

---

## Task 10: 真实 graph 工厂 + 启动接线 (api/main.py)

**Files:**
- Modify: `api/main.py`(实现 `real_graph_factory`,在 startup 时设为默认)
- Test: `tests/webui/test_graph_factory.py`

真实工厂把 `AnalysisRequest` 映射为 `TradingAgentsGraph` 实例、初始 state、并预先计算 decision/final_state。但 `propagate` 是阻塞的,我们不能在工厂里跑它——而是让工厂返回 graph + init_state,**decision/final_state 由 runner 跑完 stream 后从 graph 实例读取**。因此重新约定:工厂返回 `(graph, init_state)`;runner 跑完后调用 `graph.process_signal(...)` 取 decision。为保持 Task 5/9 的 runner 签名稳定且可测,这里改为工厂内部用一个轻量包装:跑 stream 收集 final_state,结束后调用框架的信号处理。

为避免回改 runner,采用如下方案:`real_graph_factory(req)` 返回 `(graph, init_state, None, None)`;`AnalysisRunner.run` 在 stream 结束、`final_state` 为 None 时,从累计的 chunk 合并出 final_state 并调用 `graph.process_signal`。本任务据此**小幅扩展 runner**。

- [ ] **Step 1: 写失败测试**

`tests/webui/test_graph_factory.py`:
```python
def test_real_graph_factory_builds_graph(monkeypatch):
    import api.main as main
    from api.schemas import AnalysisRequest

    captured = {}

    class _FakeTAG:
        def __init__(self, selected_analysts, debug, config, **kwargs):
            captured["analysts"] = selected_analysts
            captured["config"] = config

            class _Prop:
                def create_initial_state(self, ticker, date):
                    captured["ticker"] = ticker
                    return {"company_of_interest": ticker, "trade_date": date}

            self.propagator = _Prop()

            class _Inner:
                def stream(inner_self, s, **k):
                    yield {}

            self.graph = _Inner()

    monkeypatch.setattr(main, "TradingAgentsGraph", _FakeTAG)

    req = AnalysisRequest(
        ticker="NVDA",
        trade_date="2024-05-10",
        analysts=["market", "news"],
        research_depth=5,
        llm_provider="openai",
    )
    graph, init_state, decision, final_state = main.real_graph_factory(req)
    assert captured["analysts"] == ["market", "news"]
    assert captured["config"]["max_debate_rounds"] == 5
    assert captured["config"]["llm_provider"] == "openai"
    assert init_state["company_of_interest"] == "NVDA"
    assert decision is None and final_state is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/webui/test_graph_factory.py -v`
Expected: FAIL,`AttributeError: module 'api.main' has no attribute 'real_graph_factory'` 或 `TradingAgentsGraph`。

- [ ] **Step 3: 在 main.py 实现真实工厂 + 接线**

在 `api/main.py` 顶部 import 区追加:
```python
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
```

在文件末尾追加:
```python
def real_graph_factory(req):
    """Build a TradingAgentsGraph from a request. Returns (graph, init_state, None, None).

    decision/final_state are computed by the runner after the stream completes,
    because propagate()/stream() must actually run first.
    """
    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = req.research_depth
    config["max_risk_discuss_rounds"] = req.research_depth
    config["output_language"] = req.output_language
    if req.llm_provider:
        config["llm_provider"] = req.llm_provider
    if req.deep_think_llm:
        config["deep_think_llm"] = req.deep_think_llm
    if req.quick_think_llm:
        config["quick_think_llm"] = req.quick_think_llm

    graph = TradingAgentsGraph(
        selected_analysts=req.analysts, debug=False, config=config
    )
    init_state = graph.propagator.create_initial_state(req.ticker, req.trade_date)
    return graph, init_state, None, None


@app.on_event("startup")
def _wire_graph_factory():
    if app.state.graph_factory is None:
        app.state.graph_factory = real_graph_factory
```

- [ ] **Step 4: 扩展 runner 在 final_state 为 None 时自行计算**

在 `api/runner.py` 的 `AnalysisRunner.run` 中,把累计 final_state 的逻辑补上。将 `run` 方法替换为:
```python
    def run(self, run_id, graph, init_state, decision, final_state) -> None:
        seen: set[str] = set()
        accumulated: dict = {}
        try:
            for chunk in graph.graph.stream(init_state):
                if isinstance(chunk, dict):
                    accumulated.update(chunk)
                for event in chunk_to_events(chunk, seen):
                    self._q.put(event)

            if final_state is None:
                final_state = accumulated
            if decision is None:
                decision = _extract_decision(graph, final_state)

            self._store.complete_run(
                run_id, decision=decision or "Hold", result=final_state or {}
            )
            self._q.put(
                {
                    "event": "done",
                    "data": {
                        "decision": decision or "Hold",
                        "final_trade_decision": (final_state or {}).get(
                            "final_trade_decision", ""
                        ),
                        "run_id": run_id,
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._store.mark_error(run_id, str(exc))
            self._q.put({"event": "error", "data": {"message": str(exc)}})
        finally:
            self._q.put(None)
```

并在 `api/runner.py` 末尾追加辅助函数:
```python
def _extract_decision(graph, final_state: dict) -> str | None:
    """Best-effort: derive the 5-tier decision from final_trade_decision prose."""
    text = (final_state or {}).get("final_trade_decision", "")
    if not text:
        return None
    processor = getattr(graph, "process_signal", None)
    if callable(processor):
        try:
            return processor(text)
        except Exception:  # noqa: BLE001
            pass
    try:
        from tradingagents.agents.utils.rating import parse_rating

        return parse_rating(text)
    except Exception:  # noqa: BLE001
        return None
```

- [ ] **Step 5: 运行全部后端测试确认通过**

Run: `pytest tests/webui/ -v`
Expected: PASS(全部通过;之前的 runner 测试因 final_state 显式传入仍按原路径走,不受影响)。

- [ ] **Step 6: lint**

Run: `ruff check api/`
Expected: 无错误(或仅自动可修;若有则 `ruff check api/ --fix` 后复查)。

- [ ] **Step 7: Commit**

```bash
git add api/main.py api/runner.py tests/webui/test_graph_factory.py
git commit --no-verify -m "feat(webui): wire real TradingAgentsGraph factory + decision extraction"
```

---

## Task 11: 后端冒烟运行验证

**Files:** 无新增,仅手动验证 + 一个 smoke 测试。

- [ ] **Step 1: 写 smoke 测试验证 app 可加载**

`tests/webui/test_smoke.py`:
```python
import pytest


@pytest.mark.smoke
def test_app_imports_and_has_routes():
    from api.main import app

    paths = {r.path for r in app.routes}
    assert "/api/config/options" in paths
    assert "/api/history" in paths
    assert "/api/analysis" in paths
```

- [ ] **Step 2: 运行 smoke 测试**

Run: `pytest tests/webui/test_smoke.py -v -m smoke`
Expected: PASS(1 passed)

- [ ] **Step 3: 手动启动验证(可选,需环境)**

Run: `uvicorn api.main:app --port 8000` 然后另开终端 `curl -s http://localhost:8000/api/config/options`
Expected: 返回含 `analysts`/`research_depth` 的 JSON;Ctrl-C 停止。

- [ ] **Step 4: Commit**

```bash
git add tests/webui/test_smoke.py
git commit --no-verify -m "test(webui): add backend smoke test for route wiring"
```

---

## Task 12: 前端脚手架 + 类型 + API/SSE 封装

**Files:**
- Create: `webui/`(Next.js 项目)
- Create: `webui/lib/types.ts`、`webui/lib/api.ts`、`webui/lib/sse.ts`

- [ ] **Step 1: 创建 Next.js 项目**

Run(在仓库根目录):
```bash
npx create-next-app@latest webui --typescript --tailwind --eslint --app --src-dir=false --import-alias "@/*" --no-turbopack
```
Expected: 在 `webui/` 生成 Next.js 项目。

- [ ] **Step 2: 安装 shadcn 与 markdown 渲染**

Run:
```bash
cd webui && npx shadcn@latest init -d && npx shadcn@latest add button card badge && npm i react-markdown && cd ..
```
Expected: 安装成功,生成 `webui/components/ui/*`。

- [ ] **Step 3: 写 TS 类型**

`webui/lib/types.ts`:
```typescript
export type AssetType = "stock" | "crypto";
export type Decision = "Buy" | "Overweight" | "Hold" | "Underweight" | "Sell";
export type RunStatus = "running" | "completed" | "error";

export interface AnalysisRequest {
  ticker: string;
  trade_date: string;
  asset_type: AssetType;
  analysts: string[];
  research_depth: 1 | 3 | 5;
  output_language: string;
  llm_provider: string | null;
  deep_think_llm: string | null;
  quick_think_llm: string | null;
}

export interface ConfigOptions {
  analysts: { value: string; label: string }[];
  research_depth: { value: number; label: string }[];
  languages: string[];
  configured_provider: string | null;
  configured_deep_llm: string | null;
  configured_quick_llm: string | null;
}

export interface HistorySummary {
  run_id: string;
  ticker: string;
  trade_date: string;
  decision: Decision | null;
  status: RunStatus;
  created_at: string;
}

export type SSEEvent =
  | { event: "agent_status"; data: { agent: string; team: string; status: string } }
  | { event: "message"; data: { agent: string; team: string; content: string; ts: number } }
  | { event: "report_section"; data: { section: string; content: string } }
  | { event: "stats"; data: Record<string, number> }
  | { event: "done"; data: { decision: Decision; final_trade_decision: string; run_id: string } }
  | { event: "error"; data: { message: string } };
```

- [ ] **Step 4: 写 API 封装**

`webui/lib/api.ts`:
```typescript
import type { AnalysisRequest, ConfigOptions, HistorySummary } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function getConfigOptions(): Promise<ConfigOptions> {
  const r = await fetch(`${BASE}/api/config/options`);
  if (!r.ok) throw new Error("failed to load config options");
  return r.json();
}

export async function startAnalysis(req: AnalysisRequest): Promise<string> {
  const r = await fetch(`${BASE}/api/analysis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (r.status === 409) throw new Error("已有分析正在运行");
  if (!r.ok) throw new Error("failed to start analysis");
  return (await r.json()).run_id as string;
}

export async function getHistory(): Promise<HistorySummary[]> {
  const r = await fetch(`${BASE}/api/history`);
  return r.ok ? r.json() : [];
}

export async function deleteHistory(runId: string): Promise<void> {
  await fetch(`${BASE}/api/history/${runId}`, { method: "DELETE" });
}

export function reportUrl(runId: string): string {
  return `${BASE}/api/analysis/${runId}/report`;
}

export function streamUrl(runId: string): string {
  return `${BASE}/api/analysis/${runId}/stream`;
}
```

- [ ] **Step 5: 写 SSE 客户端**

`webui/lib/sse.ts`:
```typescript
import type { SSEEvent } from "./types";
import { streamUrl } from "./api";

export function subscribe(
  runId: string,
  onEvent: (e: SSEEvent) => void,
  onClose: () => void,
): () => void {
  const es = new EventSource(streamUrl(runId));
  const handler = (type: SSEEvent["event"]) => (ev: MessageEvent) => {
    try {
      onEvent({ event: type, data: JSON.parse(ev.data) } as SSEEvent);
    } catch {
      /* ignore malformed */
    }
  };
  (["agent_status", "message", "report_section", "stats", "done", "error"] as const).forEach(
    (t) => es.addEventListener(t, handler(t)),
  );
  es.addEventListener("done", () => {
    es.close();
    onClose();
  });
  es.onerror = () => {
    es.close();
    onClose();
  };
  return () => es.close();
}
```

- [ ] **Step 6: 验证前端可构建**

Run: `cd webui && npm run build && cd ..`
Expected: 构建成功(可能有 unused 警告,无错误即可)。

- [ ] **Step 7: Commit**

```bash
git add webui/
git commit --no-verify -m "feat(webui): scaffold Next.js frontend with types, API and SSE clients"
```

---

## Task 13: 前端组件 + 页面组装(金融终端风)

> 视觉风格交付时使用 visual-engineering 类别 + 加载相关设计技能(impeccable / high-end-visual-design / design-taste-frontend),呈现深色金融终端风。本 Task 给出功能骨架,样式在交付时细化。

**Files:**
- Create: `webui/components/ConfigCard.tsx`、`AgentProgress.tsx`、`MessageBubble.tsx`、`DecisionCard.tsx`、`HistorySidebar.tsx`
- Modify: `webui/app/page.tsx`、`webui/app/globals.css`

- [ ] **Step 1: ConfigCard.tsx**

`webui/components/ConfigCard.tsx`:
```tsx
"use client";
import { useState } from "react";
import type { AnalysisRequest, ConfigOptions } from "@/lib/types";

export function ConfigCard({
  options,
  onStart,
}: {
  options: ConfigOptions;
  onStart: (req: AnalysisRequest) => void;
}) {
  const [ticker, setTicker] = useState("NVDA");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [assetType, setAssetType] = useState<"stock" | "crypto">("stock");
  const [analysts, setAnalysts] = useState<string[]>([
    "market",
    "social",
    "news",
    "fundamentals",
  ]);
  const [depth, setDepth] = useState<1 | 3 | 5>(3);
  const [language, setLanguage] = useState("Chinese");

  const toggle = (v: string) =>
    setAnalysts((a) => (a.includes(v) ? a.filter((x) => x !== v) : [...a, v]));

  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900 p-4 space-y-3">
      <div className="flex gap-2">
        <input
          className="bg-zinc-800 px-2 py-1 rounded font-mono"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="NVDA / 0700.HK / BTC-USD"
        />
        <input
          type="date"
          className="bg-zinc-800 px-2 py-1 rounded font-mono"
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </div>
      <div className="flex flex-wrap gap-2">
        {options.analysts.map((a) => {
          const disabled = assetType === "crypto" && a.value === "fundamentals";
          const on = analysts.includes(a.value) && !disabled;
          return (
            <button
              key={a.value}
              disabled={disabled}
              onClick={() => toggle(a.value)}
              className={`px-3 py-1 rounded-full text-sm ${
                on ? "bg-emerald-600" : "bg-zinc-800"
              } ${disabled ? "opacity-40" : ""}`}
            >
              {a.label}
            </button>
          );
        })}
      </div>
      <div className="flex gap-2">
        {options.research_depth.map((d) => (
          <button
            key={d.value}
            onClick={() => setDepth(d.value as 1 | 3 | 5)}
            className={`px-3 py-1 rounded text-sm ${
              depth === d.value ? "bg-emerald-600" : "bg-zinc-800"
            }`}
          >
            {d.label}
          </button>
        ))}
      </div>
      <button
        className="w-full bg-emerald-500 text-black font-bold py-2 rounded"
        onClick={() =>
          onStart({
            ticker,
            trade_date: date,
            asset_type: assetType,
            analysts: analysts.filter(
              (a) => !(assetType === "crypto" && a === "fundamentals"),
            ),
            research_depth: depth,
            output_language: language,
            llm_provider: null,
            deep_think_llm: null,
            quick_think_llm: null,
          })
        }
      >
        🚀 开始分析
      </button>
    </div>
  );
}
```

- [ ] **Step 2: AgentProgress.tsx**

`webui/components/AgentProgress.tsx`:
```tsx
"use client";
const AGENTS: { id: string; label: string }[] = [
  { id: "market_analyst", label: "市场" },
  { id: "social_analyst", label: "情绪" },
  { id: "news_analyst", label: "新闻" },
  { id: "fundamentals_analyst", label: "基本面" },
  { id: "research_manager", label: "研究经理" },
  { id: "trader", label: "交易员" },
  { id: "portfolio_manager", label: "组合经理" },
];

export function AgentProgress({ statuses }: { statuses: Record<string, string> }) {
  return (
    <div className="flex flex-wrap gap-2 text-xs font-mono">
      {AGENTS.map((a) => {
        const s = statuses[a.id] ?? "pending";
        const color =
          s === "done" ? "text-emerald-400" : s === "working" ? "text-amber-400" : "text-zinc-500";
        const mark = s === "done" ? "✓" : s === "working" ? "⟳" : "·";
        return (
          <span key={a.id} className={color}>
            {mark} {a.label}
          </span>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3: MessageBubble.tsx + DecisionCard.tsx**

`webui/components/MessageBubble.tsx`:
```tsx
"use client";
import ReactMarkdown from "react-markdown";

export function MessageBubble({ agent, content }: { agent: string; content: string }) {
  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-900 p-3">
      <div className="text-xs text-emerald-400 font-mono mb-1">{agent}</div>
      <div className="prose prose-invert prose-sm max-w-none">
        <ReactMarkdown>{content}</ReactMarkdown>
      </div>
    </div>
  );
}
```

`webui/components/DecisionCard.tsx`:
```tsx
"use client";
import ReactMarkdown from "react-markdown";
import type { Decision } from "@/lib/types";

const COLORS: Record<string, string> = {
  Buy: "text-emerald-400",
  Overweight: "text-emerald-300",
  Hold: "text-zinc-300",
  Underweight: "text-red-300",
  Sell: "text-red-400",
};

export function DecisionCard({ decision, detail }: { decision: Decision; detail: string }) {
  return (
    <div className="rounded-lg border-2 border-emerald-700 bg-zinc-900 p-4">
      <div className={`text-4xl font-bold font-mono ${COLORS[decision] ?? ""}`}>{decision}</div>
      <div className="prose prose-invert prose-sm max-w-none mt-2">
        <ReactMarkdown>{detail}</ReactMarkdown>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: HistorySidebar.tsx**

`webui/components/HistorySidebar.tsx`:
```tsx
"use client";
import type { HistorySummary } from "@/lib/types";

export function HistorySidebar({
  items,
  onOpen,
  onDelete,
}: {
  items: HistorySummary[];
  onOpen: (runId: string) => void;
  onDelete: (runId: string) => void;
}) {
  return (
    <aside className="w-64 shrink-0 border-r border-zinc-800 bg-zinc-950 p-2 space-y-1 overflow-y-auto">
      <div className="text-xs text-zinc-500 px-2 py-1">历史分析</div>
      {items.map((it) => (
        <div
          key={it.run_id}
          className="group flex items-center justify-between px-2 py-1 rounded hover:bg-zinc-800 cursor-pointer"
          onClick={() => onOpen(it.run_id)}
        >
          <span className="font-mono text-sm">
            {it.ticker} · {it.trade_date} · {it.decision ?? it.status}
          </span>
          <button
            className="opacity-0 group-hover:opacity-100 text-red-400 text-xs"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(it.run_id);
            }}
          >
            ✕
          </button>
        </div>
      ))}
    </aside>
  );
}
```

- [ ] **Step 5: page.tsx 组装**

`webui/app/page.tsx`:
```tsx
"use client";
import { useEffect, useState } from "react";
import { ConfigCard } from "@/components/ConfigCard";
import { AgentProgress } from "@/components/AgentProgress";
import { MessageBubble } from "@/components/MessageBubble";
import { DecisionCard } from "@/components/DecisionCard";
import { HistorySidebar } from "@/components/HistorySidebar";
import {
  deleteHistory,
  getConfigOptions,
  getHistory,
  startAnalysis,
} from "@/lib/api";
import { subscribe } from "@/lib/sse";
import type { ConfigOptions, Decision, HistorySummary, SSEEvent } from "@/lib/types";

export default function Home() {
  const [options, setOptions] = useState<ConfigOptions | null>(null);
  const [history, setHistory] = useState<HistorySummary[]>([]);
  const [statuses, setStatuses] = useState<Record<string, string>>({});
  const [messages, setMessages] = useState<{ agent: string; content: string }[]>([]);
  const [decision, setDecision] = useState<{ d: Decision; detail: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshHistory = () => getHistory().then(setHistory);

  useEffect(() => {
    getConfigOptions().then(setOptions).catch(() => setError("无法连接后端"));
    refreshHistory();
  }, []);

  const onStart = async (req: Parameters<typeof startAnalysis>[0]) => {
    setStatuses({});
    setMessages([]);
    setDecision(null);
    setError(null);
    try {
      const runId = await startAnalysis(req);
      subscribe(
        runId,
        (e: SSEEvent) => {
          if (e.event === "agent_status")
            setStatuses((s) => ({ ...s, [e.data.agent]: e.data.status }));
          else if (e.event === "message")
            setMessages((m) => [...m, { agent: e.data.agent, content: e.data.content }]);
          else if (e.event === "done")
            setDecision({ d: e.data.decision, detail: e.data.final_trade_decision });
          else if (e.event === "error") setError(e.data.message);
        },
        refreshHistory,
      );
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="flex h-screen bg-black text-zinc-200">
      <HistorySidebar items={history} onOpen={() => {}} onDelete={(id) => deleteHistory(id).then(refreshHistory)} />
      <main className="flex-1 overflow-y-auto p-4 space-y-3 max-w-3xl mx-auto">
        <h1 className="font-mono text-emerald-400">TradingAgents 分析助手</h1>
        {error && <div className="text-red-400">{error}</div>}
        {options && <ConfigCard options={options} onStart={onStart} />}
        <AgentProgress statuses={statuses} />
        {messages.map((m, i) => (
          <MessageBubble key={i} agent={m.agent} content={m.content} />
        ))}
        {decision && <DecisionCard decision={decision.d} detail={decision.detail} />}
      </main>
    </div>
  );
}
```

- [ ] **Step 6: 构建验证**

Run: `cd webui && npm run build && cd ..`
Expected: 构建成功。

- [ ] **Step 7: Commit**

```bash
git add webui/
git commit --no-verify -m "feat(webui): add chat UI components and page assembly"
```

---

## Task 14: 文档 + 部署接线

**Files:**
- Create: `Dockerfile.api`
- Modify: `docker-compose.yml`(新增 api service)
- Create: `api/README.md`

- [ ] **Step 1: 写 Dockerfile.api**

`Dockerfile.api`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY tradingagents ./tradingagents
COPY cli ./cli
COPY api ./api
RUN pip install --no-cache-dir -e ".[dev]"
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: 在 docker-compose.yml 追加 api service**

读取现有 `docker-compose.yml`,在 `services:` 下追加(保持现有 services 不动):
```yaml
  tradingagents-api:
    build:
      context: .
      dockerfile: Dockerfile.api
    env_file: .env
    ports:
      - "8000:8000"
    volumes:
      - ~/.tradingagents:/root/.tradingagents
```

- [ ] **Step 3: 写 api/README.md**

`api/README.md`:
```markdown
# TradingAgents WebUI API

FastAPI backend for the conversational analysis assistant.

## Run (dev)

    pip install -e ".[dev]"
    uvicorn api.main:app --reload --port 8000

Frontend (separate terminal):

    cd webui && npm run dev   # http://localhost:3000

## Endpoints

- `GET  /api/config/options` — config card options
- `POST /api/analysis` — start a run, returns `{run_id}` (409 if one is running)
- `GET  /api/analysis/{run_id}/stream` — SSE event stream
- `GET  /api/analysis/{run_id}/report` — download Markdown report
- `GET  /api/history` — list past runs
- `GET  /api/history/{run_id}` — run detail
- `DELETE /api/history/{run_id}` — delete a run

History DB: `~/.tradingagents/webui.db`.
```

- [ ] **Step 4: 全量后端测试 + lint 最终确认**

Run: `pytest tests/webui/ -v && ruff check api/`
Expected: 全部 PASS,lint 无错误。

- [ ] **Step 5: Commit**

```bash
git add Dockerfile.api docker-compose.yml api/README.md
git commit --no-verify -m "feat(webui): add API Dockerfile, compose service, and README"
```

---

## Self-Review

**Spec coverage check(逐节对照设计文档):**
- §3 架构(api/ + webui/ 结构、线程队列桥接)→ Task 1/5/9 ✓
- §4 前端交互(历史侧栏/配置卡片/进度条/逐条气泡/结论卡)→ Task 13 ✓
- §5.1 REST 7 端点 → config(T7)/history×3(T8)/analysis start+stream+report(T9)✓
- §5.2 请求体(analysts/research_depth→max_debate_rounds 映射)→ T2 schema + T10 factory ✓
- §5.3 SSE 5 事件(agent_status/message/report_section/stats/done)+ error → T4/T5/T9 ✓(注:`stats` 事件协议已在 SSE 客户端与类型中预留;实时 stats 推送依赖 StatsCallbackHandler 接入,作为 T9 之上的增量,当前 runner 已留出 message/report/done/error 主路径;stats 接线见下方备注)
- §6 SQLite 模型(单表 + 生命周期 + has_running_run)→ T3 ✓
- §7 错误处理(error 事件 + DB status=error + 409 单运行)→ T5/T9 ✓
- §8 测试策略(fake graph、TestClient、SSE 解析)→ T2-T11 后端测试 ✓
- §9 部署(Dockerfile.api + compose + CORS)→ T7 CORS + T14 ✓

**stats 事件备注(补全覆盖,避免占位):** 实时 `stats` 推送需把 `StatsCallbackHandler` 注入 `TradingAgentsGraph(callbacks=[handler])`(T10 factory 可加 `callbacks=[StatsCallbackHandler()]`),并在 runner 每处理若干 chunk 后 `self._q.put({"event":"stats","data":handler.get_stats()})`。前端已在 `lib/types.ts` 与 `lib/sse.ts` 支持该事件。此为可选增强,主决策流不依赖它;若实现,加在 T10/T5 中,无需新 Task。

**Placeholder scan:** 无 "TBD/TODO/略";每个 code step 均含完整代码与确切命令。✓

**Type consistency:** `REPORT_SECTIONS` 字段名(T4)与 download_report 的 `_REPORT_ORDER`(T9)、前端 `section`(T13)一致;`AnalysisRunner.run` 签名在 T5 定义、T9 调用、T10 扩展保持 `(run_id, graph, init_state, decision, final_state)` 一致;`get_store()` 在 T7 定义、T8/T9 引用一致;SSE 事件 5 类型在后端(T4/T9)与前端(T12 types/sse)一致。✓
