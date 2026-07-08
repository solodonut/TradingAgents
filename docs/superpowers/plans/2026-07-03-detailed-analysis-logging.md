# 详细分析日志功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每次分析生成一份逐动作的结构化 JSONL 日志文件（LLM/工具/数据源/节点/辩论/报告/memory/checkpoint/异常），并让 Web UI 实时查看 + 历史回读。

**Architecture:** 新增 `tradingagents/obs/` 子包，核心是 `RunLogger`（线程安全、追加写 JSONL、可选 sink 推 SSE）+ 一个 `ContextVar` 环境式日志器。各埋点处「取 contextvar logger，无则跳过」，不改被调函数签名。两条运行路径各自在其执行线程内设置 contextvar：CLI 走 `TradingAgentsGraph.propagate`，WebUI 走 `AnalysisRunner.run`（后者额外注入 sink → 推 `log` SSE 事件）。前端在现有 EventSource 管道加 `log` 事件 + `/logs` 回读接口。

**Tech Stack:** Python 3.10+，LangChain/LangGraph 回调，FastAPI + sse-starlette，SQLite（`api/store.py`），Next.js 16 / React 19 / vitest（`webui/`）。

## Global Constraints

- Python 命令一律用 `.venv/bin/python`（系统 python 可能 <3.10 或 NumPy 1.x）。
- Lint：`ruff check .`（行长 100，E501 已忽略）。收尾手动跑 `ruff check .` 和 `pytest -m "not integration"`。
- 数据访问只经 `dataflows/interface.py::route_to_vendor`；LLM 只经 `llm_clients/factory.py`。埋点不得改这些函数的签名。
- 埋点原则：`logger = get_current_run_logger(); if logger: logger.emit(...)`；无上下文时零副作用，不得抛错、不得影响分析结果。
- 密钥脱敏：写入日志的 config 快照与 vendor 参数须过 `redact()`。
- 提交：Conventional Commits（`feat(obs):` / `test(obs):` / `feat(webui):`）。同步维护 `CHANGELOG.md`（Keep a Changelog）。
- 改 `webui/` 前先读 `webui/node_modules/next/dist/docs/`（Next.js 16 破坏性变更）。
- 日志目录默认 `~/.tradingagents/run_logs/`（**非** spec 的 `logs/`，因 `results_dir` 已占用 `logs/`），`TRADINGAGENTS_LOG_DIR` 覆盖。
- 测试全程 mock、无网络、无真实 key（`conftest.py` 注入 placeholder key）。

---

## 文件结构

- **新建** `tradingagents/obs/__init__.py` — 导出公共 API（`RunLogger`, `get/set/clear_current_run_logger`, `create_run_logger`, `redact`, `wrap_node`, `ObsCallbackHandler`）。
- **新建** `tradingagents/obs/run_logger.py` — `RunLogger`、`redact`、`truncate`、contextvar 三函数、`build_log_path`、`create_run_logger`。
- **新建** `tradingagents/obs/callback.py` — `ObsCallbackHandler`（LLM/tool → `llm_call`/`tool_call`）。
- **新建** `tradingagents/obs/node.py` — `wrap_node(name, fn)`（`node_enter`/`node_exit`）。
- **改** `tradingagents/default_config.py` — 新增 3 个 config 键 + env 覆盖。
- **改** `tradingagents/graph/setup.py` — 用 `wrap_node` 包裹每个节点。
- **改** `tradingagents/graph/trading_graph.py` — `__init__` 挂 `ObsCallbackHandler`；`propagate` 管理 CLI 路径生命周期。
- **改** `tradingagents/dataflows/interface.py` — `route_to_vendor` 内 `vendor_call` 埋点。
- **改** `tradingagents/agents/utils/memory.py` — `memory_op` 埋点。
- **改** `tradingagents/graph/checkpointer.py` — `checkpoint_op` 埋点。
- **改** `api/store.py` — `log_path` 列 + `set_log_path`/`get_log_path`。
- **改** `api/runner.py` — WebUI 路径生命周期 + sink → 队列 `log` 事件。
- **改** `api/routes/analysis.py` — `GET /{run_id}/logs` 回读接口。
- **改** `webui/lib/sse.ts` / `lib/types.ts` / `lib/api.ts` — `log` 事件订阅 + 类型 + `getRunLogs`。
- **新建** `webui/lib/logs.ts` + `webui/lib/logs.test.ts` — `filterLogs` 纯函数 + 测试。
- **新建** `webui/components/LogPanel.tsx` — 实时着色流 + 过滤/搜索/展开。
- **改** `webui/app/page.tsx` — logs state + `log` 事件处理 + 挂载 `LogPanel`。
- **新建测试** `tests/obs/test_run_logger.py`, `tests/obs/test_callback.py`, `tests/obs/test_node.py`, `tests/obs/test_vendor_logging.py`, `tests/webui/test_logs_route.py`, `tests/webui/test_runner_logging.py`。

---

## Task 1: obs 核心 — RunLogger + contextvar + redact/truncate

**Files:**
- Create: `tradingagents/obs/__init__.py`
- Create: `tradingagents/obs/run_logger.py`
- Test: `tests/obs/__init__.py`, `tests/obs/test_run_logger.py`

**Interfaces:**
- Produces:
  - `RunLogger(run_id: str, ticker: str, path: str | Path, sink: Callable[[dict], None] | None = None, truncate_chars: int = 8000)`
    - `.emit(event_type: str, *, elapsed_ms: float | None = None, **payload) -> dict`
    - `.truncate(value) -> value | {"text","truncated","full_chars"}`
    - `.path: Path`, `.close() -> None`
  - `redact(obj) -> obj`（递归打码密钥字段）
  - `truncate(value, limit) -> ...`（模块级）
  - `get_current_run_logger() -> RunLogger | None`
  - `set_current_run_logger(logger: RunLogger | None) -> None`
  - `clear_current_run_logger() -> None`

- [ ] **Step 1: 写失败测试**

Create `tests/obs/__init__.py`（空文件）。Create `tests/obs/test_run_logger.py`:

```python
import json

from tradingagents.obs.run_logger import (
    RunLogger,
    clear_current_run_logger,
    get_current_run_logger,
    redact,
    set_current_run_logger,
)


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_emit_writes_jsonl_with_monotonic_seq(tmp_path):
    lg = RunLogger("run123", "SPY", tmp_path / "a.jsonl")
    lg.emit("run_start", ticker="SPY")
    lg.emit("node_enter", node="Trader")
    lg.close()
    events = _read(tmp_path / "a.jsonl")
    assert [e["seq"] for e in events] == [1, 2]
    assert events[0]["event_type"] == "run_start"
    assert events[0]["run_id"] == "run123"
    assert "ts" in events[0]
    assert events[1]["node"] == "Trader"


def test_truncate_long_strings(tmp_path):
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl", truncate_chars=5)
    out = lg.truncate("abcdefgh")
    assert out == {"text": "abcde", "truncated": True, "full_chars": 8}
    assert lg.truncate("abc") == "abc"
    lg.close()


def test_redact_masks_secret_keys():
    got = redact({"api_key": "sk-1", "openai_key": "x", "nested": {"authorization": "b", "ok": 1}})
    assert got == {"api_key": "***", "openai_key": "***", "nested": {"authorization": "***", "ok": 1}}


def test_sink_called_and_exception_swallowed(tmp_path):
    seen = []
    def bad_sink(ev):
        seen.append(ev)
        raise RuntimeError("boom")
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl", sink=bad_sink)
    ev = lg.emit("x", foo=1)  # must not raise
    lg.close()
    assert seen and seen[0]["foo"] == 1
    assert ev["event_type"] == "x"


def test_contextvar_set_get_clear(tmp_path):
    assert get_current_run_logger() is None
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    assert get_current_run_logger() is lg
    clear_current_run_logger()
    assert get_current_run_logger() is None
    lg.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/obs/test_run_logger.py -v`
Expected: FAIL（`ModuleNotFoundError: tradingagents.obs`）

- [ ] **Step 3: 实现 run_logger.py**

Create `tradingagents/obs/run_logger.py`:

```python
"""Per-run structured JSONL logger + contextvar-based ambient access."""

from __future__ import annotations

import json
import threading
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_REDACT_SUBSTRINGS = ("api_key", "authorization", "token", "secret", "password")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _looks_secret(key: str) -> bool:
    k = key.lower()
    return k.endswith("_key") or any(s in k for s in _REDACT_SUBSTRINGS)


def redact(obj: Any) -> Any:
    """Recursively mask values whose key name looks like a secret."""
    if isinstance(obj, dict):
        return {k: ("***" if _looks_secret(str(k)) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj


def truncate(value: Any, limit: int) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return {"text": value[:limit], "truncated": True, "full_chars": len(value)}
    return value


class RunLogger:
    """Thread-safe append-only JSONL writer for one analysis run.

    ``sink`` (optional) is invoked with each event dict after it is written to
    disk — the WebUI passes a function that pushes the event onto the SSE queue.
    A failing sink never propagates: the file remains the source of truth.
    """

    def __init__(
        self,
        run_id: str,
        ticker: str,
        path: str | Path,
        sink: Callable[[dict], None] | None = None,
        truncate_chars: int = 8000,
    ):
        self.run_id = run_id
        self.ticker = ticker
        self.path = Path(path)
        self._sink = sink
        self._truncate_chars = truncate_chars
        self._lock = threading.Lock()
        self._seq = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def truncate(self, value: Any) -> Any:
        return truncate(value, self._truncate_chars)

    def emit(self, event_type: str, *, elapsed_ms: float | None = None, **payload) -> dict:
        with self._lock:
            self._seq += 1
            event: dict[str, Any] = {
                "ts": _now_iso(),
                "seq": self._seq,
                "run_id": self.run_id,
                "event_type": event_type,
            }
            if elapsed_ms is not None:
                event["elapsed_ms"] = elapsed_ms
            event.update(payload)
            self._fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._fh.flush()
        if self._sink is not None:
            try:
                self._sink(event)
            except Exception:  # noqa: BLE001 - sink failure must not break the run
                traceback.print_exc()
        return event

    def close(self) -> None:
        with self._lock:
            try:
                self._fh.close()
            except Exception:  # noqa: BLE001
                pass


_current: ContextVar["RunLogger | None"] = ContextVar("run_logger", default=None)


def set_current_run_logger(logger: "RunLogger | None") -> None:
    _current.set(logger)


def get_current_run_logger() -> "RunLogger | None":
    return _current.get()


def clear_current_run_logger() -> None:
    _current.set(None)
```

Create `tradingagents/obs/__init__.py`:

```python
"""Observability: per-run structured logging for analysis pipelines."""

from tradingagents.obs.run_logger import (
    RunLogger,
    clear_current_run_logger,
    get_current_run_logger,
    redact,
    set_current_run_logger,
    truncate,
)

__all__ = [
    "RunLogger",
    "clear_current_run_logger",
    "get_current_run_logger",
    "redact",
    "set_current_run_logger",
    "truncate",
]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/obs/test_run_logger.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add tradingagents/obs/ tests/obs/
git commit -m "feat(obs): add RunLogger with JSONL sink, redact, and contextvar access"
```

---

## Task 2: config 键 + create_run_logger 工厂

**Files:**
- Modify: `tradingagents/default_config.py`
- Modify: `tradingagents/obs/run_logger.py`（追加 `build_log_path` + `create_run_logger`）
- Modify: `tradingagents/obs/__init__.py`（导出二者）
- Test: `tests/obs/test_run_logger.py`（追加用例）

**Interfaces:**
- Consumes: `RunLogger`（Task 1）
- Produces:
  - `build_log_path(log_dir: str, ticker: str, run_id: str, now: datetime | None = None) -> Path`
    - 文件名 `<TICKER>_<YYYYMMDD-HHMMSS>_<run_id[:8]>.jsonl`
  - `create_run_logger(config: dict, run_id: str, ticker: str, sink=None) -> RunLogger | None`
    - `config["log_enabled"] is False` → `None`
  - `DEFAULT_CONFIG` 新增键：`log_enabled: bool=True`, `log_dir: str`, `log_truncate_chars: int=8000`
  - env 覆盖：`TRADINGAGENTS_LOG_ENABLED`, `TRADINGAGENTS_LOG_DIR`, `TRADINGAGENTS_LOG_TRUNCATE_CHARS`

- [ ] **Step 1: 写失败测试**（追加到 `tests/obs/test_run_logger.py` 末尾）

```python
from datetime import datetime

from tradingagents.obs.run_logger import build_log_path, create_run_logger


def test_build_log_path_format():
    p = build_log_path("/tmp/x", "SPY", "a1b2c3d4e5f6", now=datetime(2026, 7, 3, 14, 25, 30))
    assert p.name == "SPY_20260703-142530_a1b2c3d4.jsonl"
    assert str(p.parent) == "/tmp/x"


def test_create_run_logger_disabled_returns_none(tmp_path):
    cfg = {"log_enabled": False, "log_dir": str(tmp_path)}
    assert create_run_logger(cfg, "r", "SPY") is None


def test_create_run_logger_builds_logger(tmp_path):
    cfg = {"log_enabled": True, "log_dir": str(tmp_path), "log_truncate_chars": 10}
    lg = create_run_logger(cfg, "abcdef12", "QQQ")
    assert lg is not None
    assert lg.path.parent == tmp_path
    assert lg.truncate("x" * 20)["truncated"] is True
    lg.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/obs/test_run_logger.py -v -k "build_log_path or create_run_logger"`
Expected: FAIL（`ImportError: cannot import name 'build_log_path'`）

- [ ] **Step 3: 实现**

在 `tradingagents/obs/run_logger.py` 末尾追加：

```python
import os


def _default_log_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".tradingagents", "run_logs")


def build_log_path(log_dir: str, ticker: str, run_id: str, now: "datetime | None" = None) -> Path:
    now = now or datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in ticker) or "UNKNOWN"
    return Path(log_dir).expanduser() / f"{safe}_{stamp}_{run_id[:8]}.jsonl"


def create_run_logger(config: dict, run_id: str, ticker: str, sink=None) -> "RunLogger | None":
    if not config.get("log_enabled", True):
        return None
    log_dir = config.get("log_dir") or _default_log_dir()
    path = build_log_path(log_dir, ticker, run_id)
    return RunLogger(
        run_id, ticker, path, sink=sink,
        truncate_chars=int(config.get("log_truncate_chars", 8000)),
    )
```

在 `tradingagents/obs/__init__.py` 的 import 与 `__all__` 中加入 `build_log_path`, `create_run_logger`。

在 `tradingagents/default_config.py` 的 `_ENV_OVERRIDES` 字典末尾追加三行：

```python
    "TRADINGAGENTS_LOG_ENABLED":          "log_enabled",
    "TRADINGAGENTS_LOG_DIR":              "log_dir",
    "TRADINGAGENTS_LOG_TRUNCATE_CHARS":   "log_truncate_chars",
```

在 `DEFAULT_CONFIG = _apply_env_overrides({ ... })` 内（`memory_log_max_entries` 附近）加入：

```python
    # Detailed per-run structured logging (JSONL). One file per analysis.
    # log_dir defaults to ~/.tradingagents/run_logs/ (NOT results_dir's logs/).
    "log_enabled": True,
    "log_dir": os.getenv("TRADINGAGENTS_LOG_DIR", os.path.join(_TRADINGAGENTS_HOME, "run_logs")),
    "log_truncate_chars": 8000,
```

> 注意：`log_dir` 用 `os.getenv` 直接取，与 `results_dir` 同风格；`_ENV_OVERRIDES` 里的 `TRADINGAGENTS_LOG_DIR` 是二次保险（对 `str` 无副作用）。`log_enabled`/`log_truncate_chars` 依赖 `_ENV_OVERRIDES` 的类型感知 coercion。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/obs/test_run_logger.py -v`
Expected: PASS（8 passed）。再跑 `.venv/bin/python -c "from tradingagents.default_config import DEFAULT_CONFIG as c; print(c['log_enabled'], c['log_dir'], c['log_truncate_chars'])"` 确认键存在。

- [ ] **Step 5: 提交**

```bash
git add tradingagents/obs/ tradingagents/default_config.py tests/obs/test_run_logger.py
git commit -m "feat(obs): add create_run_logger factory and log_* config keys"
```

---

## Task 3: LLM/工具回调 ObsCallbackHandler + 挂载

**Files:**
- Create: `tradingagents/obs/callback.py`
- Modify: `tradingagents/obs/__init__.py`（导出 `ObsCallbackHandler`）
- Modify: `tradingagents/graph/trading_graph.py`（`__init__` 无条件追加 handler）
- Test: `tests/obs/test_callback.py`

**Interfaces:**
- Consumes: `get_current_run_logger`（Task 1）
- Produces: `ObsCallbackHandler()`（`langchain_core.callbacks.BaseCallbackHandler` 子类）
  - `on_chat_model_start` / `on_llm_start` 记开始（存 prompt + model + 起始时刻，键为 kwargs `run_id`）
  - `on_llm_end` 发 `llm_call`（model, prompt(截断), response(截断), tokens{in,out}, elapsed_ms）
  - `on_llm_error` 发 `error`（error_type, message, phase="llm"）
  - `on_tool_start` / `on_tool_end` 发 `tool_call`（name, args(截断), result(截断), elapsed_ms）

- [ ] **Step 1: 写失败测试**

Create `tests/obs/test_callback.py`:

```python
import json
from types import SimpleNamespace

from tradingagents.obs.callback import ObsCallbackHandler
from tradingagents.obs.run_logger import (
    RunLogger,
    clear_current_run_logger,
    set_current_run_logger,
)


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_no_logger_context_is_noop():
    clear_current_run_logger()
    cb = ObsCallbackHandler()
    # Must not raise when no logger is in context.
    cb.on_llm_start({"name": "m"}, ["hi"], run_id="x")
    cb.on_llm_end(SimpleNamespace(generations=[], llm_output={}), run_id="x")


def test_llm_call_emitted_on_end(tmp_path):
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    cb = ObsCallbackHandler()
    cb.on_chat_model_start({"name": "gpt"}, [[SimpleNamespace(content="prompt text")]], run_id="u1")
    gen = SimpleNamespace(text="answer", message=SimpleNamespace(content="answer"))
    resp = SimpleNamespace(
        generations=[[gen]],
        llm_output={"token_usage": {"prompt_tokens": 3, "completion_tokens": 2}},
    )
    cb.on_llm_end(resp, run_id="u1")
    lg.close()
    clear_current_run_logger()
    events = [e for e in _read(tmp_path / "a.jsonl") if e["event_type"] == "llm_call"]
    assert len(events) == 1
    assert events[0]["response"] == "answer"
    assert events[0]["tokens"] == {"in": 3, "out": 2}
    assert "prompt text" in json.dumps(events[0]["prompt"])


def test_tool_call_emitted(tmp_path):
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    cb = ObsCallbackHandler()
    cb.on_tool_start({"name": "get_news"}, "AAPL", run_id="t1")
    cb.on_tool_end("some news", run_id="t1")
    lg.close()
    clear_current_run_logger()
    events = [e for e in _read(tmp_path / "a.jsonl") if e["event_type"] == "tool_call"]
    assert len(events) == 1
    assert events[0]["name"] == "get_news"
    assert events[0]["args"] == "AAPL"
    assert events[0]["result"] == "some news"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/obs/test_callback.py -v`
Expected: FAIL（`ModuleNotFoundError: tradingagents.obs.callback`）

- [ ] **Step 3: 实现 callback.py**

Create `tradingagents/obs/callback.py`:

```python
"""LangChain callback → RunLogger llm_call / tool_call events (contextvar-based)."""

from __future__ import annotations

import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from tradingagents.obs.run_logger import get_current_run_logger


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part) for part in content)
    return str(content)


def _messages_text(messages: list) -> str:
    flat = [m for batch in messages for m in batch]
    return "\n\n".join(_content_text(getattr(m, "content", m)) for m in flat)


def _model_from(serialized: dict | None, kwargs: dict) -> str | None:
    params = kwargs.get("invocation_params") or {}
    for key in ("model", "model_name"):
        if params.get(key):
            return str(params[key])
    if serialized:
        blob = serialized.get("kwargs") or {}
        for key in ("model", "model_name"):
            if blob.get(key):
                return str(blob[key])
        name = serialized.get("name") or serialized.get("id")
        if name:
            return str(name)
    return None


class ObsCallbackHandler(BaseCallbackHandler):
    """Emits llm_call / tool_call events when a RunLogger is in context.

    Keyed on LangChain's per-invocation ``run_id`` so concurrent calls (the
    analyst concurrency path) don't cross their timings.
    """

    def __init__(self) -> None:
        self._llm: dict[Any, dict] = {}
        self._tool: dict[Any, dict] = {}

    def on_llm_start(self, serialized, prompts, *, run_id=None, **kwargs) -> None:
        if get_current_run_logger() is None:
            return
        self._llm[run_id] = {
            "t": time.time(),
            "model": _model_from(serialized, kwargs),
            "prompt": "\n\n".join(str(p) for p in (prompts or [])),
        }

    def on_chat_model_start(self, serialized, messages, *, run_id=None, **kwargs) -> None:
        if get_current_run_logger() is None:
            return
        self._llm[run_id] = {
            "t": time.time(),
            "model": _model_from(serialized, kwargs),
            "prompt": _messages_text(messages),
        }

    def on_llm_end(self, response, *, run_id=None, **kwargs) -> None:
        lg = get_current_run_logger()
        if lg is None:
            return
        start = self._llm.pop(run_id, None) or {}
        elapsed = (time.time() - start["t"]) * 1000 if start.get("t") else None
        text = ""
        try:
            parts = []
            for batch in getattr(response, "generations", []) or []:
                for gen in batch:
                    parts.append(getattr(gen, "text", "") or _content_text(
                        getattr(getattr(gen, "message", None), "content", "")))
            text = "\n".join(p for p in parts if p)
        except Exception:  # noqa: BLE001
            text = str(response)
        tokens: dict = {}
        try:
            usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
            tokens = {"in": usage.get("prompt_tokens"), "out": usage.get("completion_tokens")}
        except Exception:  # noqa: BLE001
            pass
        lg.emit(
            "llm_call",
            model=start.get("model"),
            prompt=lg.truncate(start.get("prompt", "")),
            response=lg.truncate(text),
            tokens=tokens,
            elapsed_ms=elapsed,
        )

    def on_llm_error(self, error, *, run_id=None, **kwargs) -> None:
        lg = get_current_run_logger()
        if lg is None:
            return
        self._llm.pop(run_id, None)
        lg.emit("error", phase="llm", error_type=type(error).__name__, message=str(error))

    def on_tool_start(self, serialized, input_str, *, run_id=None, **kwargs) -> None:
        if get_current_run_logger() is None:
            return
        self._tool[run_id] = {
            "t": time.time(),
            "name": (serialized or {}).get("name"),
            "args": input_str,
        }

    def on_tool_end(self, output, *, run_id=None, **kwargs) -> None:
        lg = get_current_run_logger()
        if lg is None:
            return
        start = self._tool.pop(run_id, None) or {}
        elapsed = (time.time() - start["t"]) * 1000 if start.get("t") else None
        lg.emit(
            "tool_call",
            name=start.get("name"),
            args=lg.truncate(str(start.get("args", ""))),
            result=lg.truncate(_content_text(output)),
            elapsed_ms=elapsed,
        )
```

在 `tradingagents/obs/__init__.py` 的 import 与 `__all__` 加入 `ObsCallbackHandler`（`from tradingagents.obs.callback import ObsCallbackHandler`）。

- [ ] **Step 4: 挂载到 graph**

在 `tradingagents/graph/trading_graph.py` 的 `__init__`（`self.callbacks = callbacks or []` 之后，约 line 83）追加：

```python
        # Always attach the observability handler; it is a no-op unless a
        # RunLogger is set in the current contextvar (CLI propagate / WebUI runner).
        from tradingagents.obs import ObsCallbackHandler

        self.callbacks = [*self.callbacks, ObsCallbackHandler()]
```

（此后 line ~96 的 `if self.callbacks: llm_kwargs["callbacks"] = self.callbacks` 自动把它传给两个 LLM 客户端。）

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/obs/test_callback.py -v`
Expected: PASS（3 passed）

- [ ] **Step 6: 提交**

```bash
git add tradingagents/obs/ tradingagents/graph/trading_graph.py tests/obs/test_callback.py
git commit -m "feat(obs): log LLM and tool calls via always-on callback handler"
```

---

## Task 4: 节点包装 — node_enter / node_exit

**Files:**
- Create: `tradingagents/obs/node.py`
- Modify: `tradingagents/obs/__init__.py`（导出 `wrap_node`）
- Modify: `tradingagents/graph/setup.py`（每个 `add_node` 用 `wrap_node` 包裹）
- Test: `tests/obs/test_node.py`

**Interfaces:**
- Consumes: `get_current_run_logger`
- Produces: `wrap_node(name: str, fn: Callable) -> Callable`
  - 有 logger：发 `node_enter{node}` → 调 fn → 发 `node_exit{node, elapsed_ms}`；异常发 `error{node,...}` 后 re-raise。
  - 无 logger：直接透传 `fn`。

- [ ] **Step 1: 写失败测试**

Create `tests/obs/test_node.py`:

```python
import json

import pytest

from tradingagents.obs.node import wrap_node
from tradingagents.obs.run_logger import (
    RunLogger,
    clear_current_run_logger,
    set_current_run_logger,
)


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_wrap_node_passthrough_without_logger():
    clear_current_run_logger()
    wrapped = wrap_node("Trader", lambda s: {"ok": s})
    assert wrapped(1) == {"ok": 1}


def test_wrap_node_emits_enter_exit(tmp_path):
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    wrapped = wrap_node("Trader", lambda s: {"v": 2})
    assert wrapped({}) == {"v": 2}
    lg.close()
    clear_current_run_logger()
    types = [e["event_type"] for e in _read(tmp_path / "a.jsonl")]
    assert types == ["node_enter", "node_exit"]


def test_wrap_node_emits_error_and_reraises(tmp_path):
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)

    def boom(_):
        raise ValueError("nope")

    with pytest.raises(ValueError):
        wrap_node("Trader", boom)({})
    lg.close()
    clear_current_run_logger()
    types = [e["event_type"] for e in _read(tmp_path / "a.jsonl")]
    assert types == ["node_enter", "error"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/obs/test_node.py -v`
Expected: FAIL（`ModuleNotFoundError: tradingagents.obs.node`）

- [ ] **Step 3: 实现 node.py**

Create `tradingagents/obs/node.py`:

```python
"""Wrap LangGraph node callables to emit node_enter / node_exit events."""

from __future__ import annotations

import time
from typing import Callable

from tradingagents.obs.run_logger import get_current_run_logger


def wrap_node(name: str, fn: Callable) -> Callable:
    def wrapped(state, *args, **kwargs):
        lg = get_current_run_logger()
        if lg is None:
            return fn(state, *args, **kwargs)
        lg.emit("node_enter", node=name)
        start = time.time()
        try:
            result = fn(state, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - log then re-raise; never swallow
            lg.emit("error", node=name, error_type=type(exc).__name__, message=str(exc))
            raise
        lg.emit("node_exit", node=name, elapsed_ms=(time.time() - start) * 1000)
        return result

    return wrapped
```

在 `tradingagents/obs/__init__.py` 的 import 与 `__all__` 加入 `wrap_node`（`from tradingagents.obs.node import wrap_node`）。

- [ ] **Step 4: 在 setup.py 应用**

在 `tradingagents/graph/setup.py` 顶部加 `from tradingagents.obs import wrap_node`。把 line 94–107 的每个 `add_node` 改为用 `wrap_node` 包裹第二个实参。逐行改写：

```python
            workflow.add_node(spec.agent_node, wrap_node(spec.agent_node, analyst_factories[spec.key]()))
            workflow.add_node(spec.clear_node, wrap_node(spec.clear_node, create_msg_delete()))
            workflow.add_node(spec.tool_node, wrap_node(spec.tool_node, self.tool_nodes[spec.key]))
```
```python
        workflow.add_node("Bull Researcher", wrap_node("Bull Researcher", bull_researcher_node))
        workflow.add_node("Bear Researcher", wrap_node("Bear Researcher", bear_researcher_node))
        workflow.add_node("Research Manager", wrap_node("Research Manager", research_manager_node))
        workflow.add_node("Trader", wrap_node("Trader", trader_node))
        workflow.add_node("Aggressive Analyst", wrap_node("Aggressive Analyst", aggressive_analyst))
        workflow.add_node("Neutral Analyst", wrap_node("Neutral Analyst", neutral_analyst))
        workflow.add_node("Conservative Analyst", wrap_node("Conservative Analyst", conservative_analyst))
        workflow.add_node("Portfolio Manager", wrap_node("Portfolio Manager", portfolio_manager_node))
        workflow.add_node("Report Validator", wrap_node("Report Validator", report_validator_node))
```

> 若 `tool_node` 是 LangGraph `ToolNode` 实例（可调用对象），`wrap_node` 以 `fn(state)` 调用它仍有效（`ToolNode.__call__(state)`）。测试见 Step 5 的 smoke import。

- [ ] **Step 5: 跑测试确认通过 + graph 构建 smoke**

Run: `.venv/bin/python -m pytest tests/obs/test_node.py -v`
Expected: PASS（3 passed）
Run: `.venv/bin/python -m pytest tests/webui/test_smoke.py -v`（确认 graph/路由仍能构建导入）
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add tradingagents/obs/ tradingagents/graph/setup.py tests/obs/test_node.py
git commit -m "feat(obs): emit node_enter/node_exit around every graph node"
```

---

## Task 5: 数据源埋点 — vendor_call

**Files:**
- Modify: `tradingagents/dataflows/interface.py`（`route_to_vendor`）
- Test: `tests/obs/test_vendor_logging.py`

**Interfaces:**
- Consumes: `get_current_run_logger`
- Produces（无新签名）：`route_to_vendor` 在有 logger 上下文时，对每个 vendor 尝试发 `vendor_call`：
  - 成功：`{method, vendor, ok=True, fallback: bool, elapsed_ms, args(截断)}`
  - 异常/未配置/限流：`{method, vendor, ok=False, error, elapsed_ms}`
  - 最终 NO_DATA：`{method, vendor=None, ok=False, no_data=True}`

- [ ] **Step 1: 写失败测试**

Create `tests/obs/test_vendor_logging.py`:

```python
import json

from tradingagents.dataflows import interface
from tradingagents.obs.run_logger import (
    RunLogger,
    clear_current_run_logger,
    set_current_run_logger,
)


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_vendor_call_logged_on_success(tmp_path, monkeypatch):
    # Register a fake method+vendor so route_to_vendor takes the success path.
    monkeypatch.setitem(interface.VENDOR_METHODS, "fake_m", {"vA": lambda *a, **k: "RESULT"})
    monkeypatch.setattr(interface, "get_category_for_method", lambda m: "core_stock_apis")
    monkeypatch.setattr(interface, "get_vendor", lambda cat, m: "vA")
    monkeypatch.setattr(interface, "get_config", lambda: {"akshare_auto_route": False})

    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    assert interface.route_to_vendor("fake_m", "SPY") == "RESULT"
    lg.close()
    clear_current_run_logger()

    events = [e for e in _read(tmp_path / "a.jsonl") if e["event_type"] == "vendor_call"]
    assert len(events) == 1
    assert events[0]["method"] == "fake_m"
    assert events[0]["vendor"] == "vA"
    assert events[0]["ok"] is True


def test_vendor_call_no_logger_is_noop(tmp_path, monkeypatch):
    monkeypatch.setitem(interface.VENDOR_METHODS, "fake_m", {"vA": lambda *a, **k: "R"})
    monkeypatch.setattr(interface, "get_category_for_method", lambda m: "core_stock_apis")
    monkeypatch.setattr(interface, "get_vendor", lambda cat, m: "vA")
    monkeypatch.setattr(interface, "get_config", lambda: {"akshare_auto_route": False})
    clear_current_run_logger()
    assert interface.route_to_vendor("fake_m", "SPY") == "R"  # must not raise
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/obs/test_vendor_logging.py -v`
Expected: FAIL（`test_vendor_call_logged_on_success` 断言 vendor_call 事件不存在）

- [ ] **Step 3: 实现埋点**

在 `tradingagents/dataflows/interface.py`：顶部（`logger = logging.getLogger(__name__)` 之后）加 import：

```python
from tradingagents.obs.run_logger import get_current_run_logger
```

在 `route_to_vendor` 进入 `for vendor in vendor_chain:` 循环之前（约 line 295 `last_no_data = ...` 附近）加：

```python
    _run_logger = get_current_run_logger()
    _t0 = time.time()

    def _emit_vendor(vendor, ok, **extra):
        if _run_logger is None:
            return
        _run_logger.emit(
            "vendor_call",
            method=method,
            vendor=vendor,
            ok=ok,
            args=_run_logger.truncate(str(args)),
            elapsed_ms=(time.time() - _t0) * 1000,
            **extra,
        )
```

> 顶部若无 `import time`，加上。

成功返回处（line 320 `return result` 之前）：

```python
            _emit_vendor(vendor, True, fallback=(vendor != vendor_chain[0]))
            return result
```

三个 except 分支的 `continue` 之前各加一行（保持原 `logger.warning` 不动）：
- `except VendorRateLimitError:` → `_emit_vendor(vendor, False, error="rate_limited")`
- `except VendorNotConfiguredError as e:` → `_emit_vendor(vendor, False, error="not_configured")`
- `except NoMarketDataError as e:` → `_emit_vendor(vendor, False, error="no_data")`
- `except Exception as e:` → `_emit_vendor(vendor, False, error=str(e))`

（`get_news` 错误哨兵 `continue`（line 319）前也加 `_emit_vendor(vendor, False, error="news_error_sentinel")`。）

NO_DATA 最终返回处（line 362 `return (` 之前）：

```python
        _emit_vendor(None, False, no_data=True)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/obs/test_vendor_logging.py -v`
Expected: PASS（2 passed）
Run: `.venv/bin/python -m pytest -m unit -k "dataflow or vendor or interface"` 确认未破坏现有路由测试。
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tradingagents/dataflows/interface.py tests/obs/test_vendor_logging.py
git commit -m "feat(obs): log every route_to_vendor attempt as vendor_call"
```

---

## Task 6: memory_op + checkpoint_op 埋点

**Files:**
- Modify: `tradingagents/agents/utils/memory.py`
- Modify: `tradingagents/graph/checkpointer.py`
- Test: `tests/obs/test_memory_checkpoint_logging.py`

**Interfaces:**
- Consumes: `get_current_run_logger`
- Produces（无新签名）：
  - `memory.py::store_decision` → `memory_op{op="append", ticker}`
  - `memory.py::get_past_context` → `memory_op{op="inject", ticker, chars}`
  - `memory.py::update_with_outcome` / `batch_update_with_outcomes` → `memory_op{op="reflect", ticker}`
  - `checkpointer.py::checkpoint_step` → `checkpoint_op{op="resume_check", ticker, step}`
  - `checkpointer.py::clear_checkpoint` → `checkpoint_op{op="clear", ticker}`

- [ ] **Step 1: 写失败测试**

Create `tests/obs/test_memory_checkpoint_logging.py`:

```python
import json

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.obs.run_logger import (
    RunLogger,
    clear_current_run_logger,
    set_current_run_logger,
)


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_store_decision_emits_memory_op(tmp_path):
    mem = TradingMemoryLog({"memory_log_path": str(tmp_path / "mem.md"), "memory_log_max_entries": None})
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    mem.store_decision(ticker="SPY", trade_date="2026-07-03", final_trade_decision="BUY")
    lg.close()
    clear_current_run_logger()
    ops = [e for e in _read(tmp_path / "a.jsonl") if e["event_type"] == "memory_op"]
    assert any(o["op"] == "append" and o["ticker"] == "SPY" for o in ops)


def test_get_past_context_emits_inject(tmp_path):
    mem = TradingMemoryLog({"memory_log_path": str(tmp_path / "mem.md"), "memory_log_max_entries": None})
    lg = RunLogger("r", "SPY", tmp_path / "a.jsonl")
    set_current_run_logger(lg)
    mem.get_past_context("SPY")
    lg.close()
    clear_current_run_logger()
    ops = [e for e in _read(tmp_path / "a.jsonl") if e["event_type"] == "memory_op"]
    assert any(o["op"] == "inject" for o in ops)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/obs/test_memory_checkpoint_logging.py -v`
Expected: FAIL（memory_op 事件不存在）

- [ ] **Step 3: 实现埋点**

在 `tradingagents/agents/utils/memory.py` 顶部加：

```python
from tradingagents.obs.run_logger import get_current_run_logger


def _emit_memory(op: str, **extra) -> None:
    lg = get_current_run_logger()
    if lg is not None:
        lg.emit("memory_op", op=op, **extra)
```

- `store_decision`（写文件后，line 49 `f.write(entry)` 之后、方法返回前）加：`_emit_memory("append", ticker=ticker)`
- `get_past_context`（`return` 之前，用组装好的字符串长度）加：`_emit_memory("inject", ticker=ticker, chars=len(result))`
  > 注意变量名：确认该方法最终返回的字符串变量（如 `"\n".join(parts)`）。若无中间变量，先 `result = "\n".join(parts)` 再 `_emit_memory("inject", ticker=ticker, chars=len(result))` 再 `return result`。
- `update_with_outcome`（原子写后返回前）加：`_emit_memory("reflect", ticker=ticker)`
  > 用该方法实际的 ticker 形参名（查看签名，line 99 起）。
- `batch_update_with_outcomes`（写后返回前）加：`_emit_memory("reflect", count=len(updates))`

在 `tradingagents/graph/checkpointer.py` 顶部加同样的 import + helper：

```python
from tradingagents.obs.run_logger import get_current_run_logger


def _emit_checkpoint(op: str, **extra) -> None:
    lg = get_current_run_logger()
    if lg is not None:
        lg.emit("checkpoint_op", op=op, **extra)
```

- `checkpoint_step`（返回 step 前）加：`_emit_checkpoint("resume_check", ticker=ticker, step=step)`
  > 若有多处 return，取最终计算出 `step` 的 return 前。
- `clear_checkpoint`（函数末尾）加：`_emit_checkpoint("clear", ticker=ticker)`

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/obs/test_memory_checkpoint_logging.py -v`
Expected: PASS（2 passed）
Run: `.venv/bin/python -m pytest -m unit -k "memory or checkpoint"` 确认现有测试不回归。
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tradingagents/agents/utils/memory.py tradingagents/graph/checkpointer.py tests/obs/test_memory_checkpoint_logging.py
git commit -m "feat(obs): log memory_op and checkpoint_op events"
```

---

## Task 7: CLI 路径生命周期 — propagate

**Files:**
- Modify: `tradingagents/graph/trading_graph.py`（`propagate`）
- Test: `tests/obs/test_propagate_lifecycle.py`

**Interfaces:**
- Consumes: `create_run_logger`, `set_current_run_logger`, `clear_current_run_logger`, `get_current_run_logger`, `redact`
- Produces（无新签名）：`propagate` 在**无既有 logger 上下文**且 `log_enabled` 时，自建 RunLogger（`sink=None`），set contextvar，发 `run_start`，结束发 `run_end`，finally clear + close。既有上下文（WebUI）时不介入。

- [ ] **Step 1: 写失败测试**

Create `tests/obs/test_propagate_lifecycle.py`:

```python
import json
from pathlib import Path

from tradingagents.obs import run_logger as rl


def test_propagate_creates_run_log(tmp_path, monkeypatch):
    """propagate wraps _run_graph with a RunLogger when none is in context."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    # Build a minimal fake that reuses only the logging wrapper logic.
    class FakeGraph(TradingAgentsGraph):
        def __init__(self):  # bypass heavy __init__
            self.config = {"log_enabled": True, "log_dir": str(tmp_path), "log_truncate_chars": 8000}
            self._checkpointer_ctx = None

        def _resolve_pending_entries(self, t):
            pass

        def _run_graph(self, company_name, trade_date, asset_type="stock"):
            # Inside the run, a logger must be active.
            assert rl.get_current_run_logger() is not None
            return ({"final_trade_decision": "BUY"}, "BUY")

    g = FakeGraph()
    final_state, signal = g.propagate("SPY", "2026-07-03")
    assert signal == "BUY"
    assert rl.get_current_run_logger() is None  # cleared afterwards

    files = list(Path(tmp_path).glob("SPY_*.jsonl"))
    assert len(files) == 1
    types = [json.loads(l)["event_type"] for l in files[0].read_text().splitlines() if l]
    assert types[0] == "run_start"
    assert "run_end" in types
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/obs/test_propagate_lifecycle.py -v`
Expected: FAIL（无 `SPY_*.jsonl` 生成 / `get_current_run_logger` 断言失败）

- [ ] **Step 3: 实现**

在 `tradingagents/graph/trading_graph.py` 顶部加 import：

```python
from tradingagents.obs import (
    clear_current_run_logger,
    create_run_logger,
    get_current_run_logger,
    redact,
    set_current_run_logger,
)
```

改 `propagate`（line 365 起）：在方法体最前面（`self.ticker = company_name` 之后）自建 logger，并把现有 `try/finally`（checkpointer）包进 logger 生命周期：

```python
        self.ticker = company_name

        import uuid as _uuid

        own_logger = None
        if get_current_run_logger() is None:
            own_logger = create_run_logger(self.config, _uuid.uuid4().hex, str(company_name))
            if own_logger is not None:
                set_current_run_logger(own_logger)
                own_logger.emit(
                    "run_start",
                    ticker=str(company_name),
                    trade_date=str(trade_date),
                    config=redact(dict(self.config)),
                )

        try:
            # Resolve any pending memory-log entries for this ticker before the pipeline runs.
            self._resolve_pending_entries(company_name)

            if self.config.get("checkpoint_enabled"):
                self._checkpointer_ctx = get_checkpointer(
                    self.config["data_cache_dir"], company_name
                )
                saver = self._checkpointer_ctx.__enter__()
                self.graph = self.workflow.compile(checkpointer=saver)

                step = checkpoint_step(
                    self.config["data_cache_dir"], company_name, str(trade_date)
                )
                if step is not None:
                    logger.info(
                        "Resuming from step %d for %s on %s", step, company_name, trade_date
                    )
                else:
                    logger.info("Starting fresh for %s on %s", company_name, trade_date)

            try:
                result = self._run_graph(company_name, trade_date, asset_type=asset_type)
            finally:
                if self._checkpointer_ctx is not None:
                    self._checkpointer_ctx.__exit__(None, None, None)
                    self._checkpointer_ctx = None
                    self.graph = self.workflow.compile()

            if own_logger is not None:
                own_logger.emit("run_end", decision=result[1])
            return result
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            if own_logger is not None:
                own_logger.emit("error", phase="run", error_type=type(exc).__name__, message=str(exc))
            raise
        finally:
            if own_logger is not None:
                clear_current_run_logger()
                own_logger.close()
```

> 保留原有 docstring。行为不变点：checkpointer 的进入/退出逻辑与原实现一致，只是内嵌进外层 logger 生命周期。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/obs/test_propagate_lifecycle.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: 提交**

```bash
git add tradingagents/graph/trading_graph.py tests/obs/test_propagate_lifecycle.py
git commit -m "feat(obs): manage RunLogger lifecycle in propagate (CLI path)"
```

---

## Task 8: store.py — log_path 列

**Files:**
- Modify: `api/store.py`
- Test: `tests/webui/test_logs_route.py`（本任务先加 store 层测试；路由在 Task 10）

**Interfaces:**
- Produces:
  - `Store.set_log_path(run_id: str, path: str) -> None`
  - `Store.get_log_path(run_id: str) -> str | None`
  - 迁移：`analysis_runs` 加列 `log_path TEXT`

- [ ] **Step 1: 写失败测试**

Create `tests/webui/test_logs_route.py`（先只放 store 层用例；Task 10 追加路由用例）:

```python
from api.store import Store


def test_set_and_get_log_path(tmp_path):
    store = Store(tmp_path / "webui.db")
    store.enqueue_run(
        run_id="r1", ticker="SPY", trade_date="2026-07-03",
        asset_type="stock", config={},
    )
    assert store.get_log_path("r1") is None
    store.set_log_path("r1", "/tmp/x/SPY_1.jsonl")
    assert store.get_log_path("r1") == "/tmp/x/SPY_1.jsonl"


def test_get_log_path_unknown_run(tmp_path):
    store = Store(tmp_path / "webui.db")
    assert store.get_log_path("nope") is None
```

> 确认 `enqueue_run` 签名（`api/store.py` line 271 起）以匹配调用；若参数名不同，按实际签名调整测试。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_logs_route.py -v`
Expected: FAIL（`AttributeError: 'Store' object has no attribute 'set_log_path'`）

- [ ] **Step 3: 实现**

在 `api/store.py` 的 `__init__` 迁移块（line 111–115）末尾追加：

```python
            if "log_path" not in cols:
                conn.execute("ALTER TABLE analysis_runs ADD COLUMN log_path TEXT")
```

在 `set_instrument_name`（line 148）之后加两个方法：

```python
    def set_log_path(self, run_id: str, path: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE analysis_runs SET log_path=? WHERE run_id=?",
                (path, run_id),
            )

    def get_log_path(self, run_id: str) -> str | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT log_path FROM analysis_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            return row["log_path"] if row and row["log_path"] else None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_logs_route.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add api/store.py tests/webui/test_logs_route.py
git commit -m "feat(webui): persist per-run log_path in store"
```

---

## Task 9: WebUI 路径生命周期 — AnalysisRunner + sink

**Files:**
- Modify: `api/runner.py`（`AnalysisRunner.__init__` 接收 config；`run` 管理 logger + sink）
- Modify: `api/scheduler.py`（`_launch` 把 config 传给 runner，并把 log_path 写回 store）
- Test: `tests/webui/test_runner_logging.py`

**Interfaces:**
- Consumes: `create_run_logger`, `set_current_run_logger`, `clear_current_run_logger`, `redact`；`Store.set_log_path`（Task 8）
- Produces:
  - `AnalysisRunner(store, event_queue, cancel_event=None, telemetry=None, config: dict | None = None)`
  - `run()` 内：创建 `create_run_logger(config, run_id, ticker, sink=lambda ev: q.put({"event":"log","data":ev}))`，`set_current_run_logger`，发 `run_start`，流式跑图，结束发 `run_end`，finally clear + close；创建后调用 `store.set_log_path(run_id, str(logger.path))`。
  - 队列新增 `{"event":"log","data":<event>}` 项。

- [ ] **Step 1: 写失败测试**

Create `tests/webui/test_runner_logging.py`:

```python
import json
import queue

from api.runner import AnalysisRunner
from api.store import Store


class FakeGraph:
    """Minimal graph whose stream emits one report section."""

    config = {"max_debate_rounds": 1, "max_risk_discuss_rounds": 1}
    _stream_args = {}

    class _G:
        @staticmethod
        def stream(init_state, **kwargs):
            yield {"market_report": "hello market"}

    graph = _G()

    def process_signal(self, text):
        return "Hold"


def test_runner_emits_log_events_and_writes_file(tmp_path):
    store = Store(tmp_path / "webui.db")
    store.enqueue_run(run_id="r1", ticker="SPY", trade_date="2026-07-03",
                      asset_type="stock", config={})
    q: queue.Queue = queue.Queue()
    runner = AnalysisRunner(
        store=store, event_queue=q, cancel_event=None, telemetry=None,
        config={"log_enabled": True, "log_dir": str(tmp_path), "log_truncate_chars": 8000},
    )
    runner.run(run_id="r1", graph=FakeGraph(), init_state={}, decision=None, final_state=None)

    # Drain queue; at least one "log" event must be present (run_start).
    items = []
    while True:
        it = q.get()
        if it is None:
            break
        items.append(it)
    log_events = [i for i in items if i["event"] == "log"]
    assert log_events, "expected log SSE events"
    assert log_events[0]["data"]["event_type"] == "run_start"

    # A JSONL file was written and its path persisted.
    path = store.get_log_path("r1")
    assert path is not None
    types = [json.loads(l)["event_type"] for l in open(path, encoding="utf-8") if l.strip()]
    assert "run_start" in types and "run_end" in types
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_runner_logging.py -v`
Expected: FAIL（`AnalysisRunner.__init__` 不接受 `config`）

- [ ] **Step 3: 实现 runner.py**

在 `api/runner.py` 顶部加：

```python
from tradingagents.obs import (
    clear_current_run_logger,
    create_run_logger,
    redact,
    set_current_run_logger,
)
```

改 `AnalysisRunner.__init__`（line 161）新增 `config` 形参并保存：

```python
    def __init__(
        self,
        store: Store,
        event_queue: "queue.Queue",
        cancel_event: threading.Event | None = None,
        telemetry: RunTelemetry | None = None,
        config: dict | None = None,
    ):
        self._store = store
        self._q = event_queue
        self._cancel_event = cancel_event
        self._telemetry = telemetry
        self._config = config or {}
```

改 `run`（line 173）：在方法开头（`seen: set[str] = set()` 之前）创建并激活 logger：

```python
        run_logger = create_run_logger(
            self._config, run_id, str(getattr(graph, "ticker", "") or init_state.get("company_of_interest", "RUN")),
            sink=lambda ev: self._q.put({"event": "log", "data": ev}),
        )
        if run_logger is not None:
            set_current_run_logger(run_logger)
            self._store.set_log_path(run_id, str(run_logger.path))
            run_logger.emit(
                "run_start",
                ticker=run_logger.ticker,
                config=redact(dict(getattr(graph, "config", {}) or {})),
            )
```

在方法末尾 `finally:` 块（line 232，现为 `self._q.put(None)`）改为：

```python
        finally:
            if run_logger is not None:
                run_logger.emit("run_end", decision=(decision or "Hold"))
                clear_current_run_logger()
                run_logger.close()
            self._q.put(None)
```

> `decision` 在 `try` 内可能被赋值；`finally` 里用 `locals().get("decision")` 更稳妥。若担心 `NameError`，改为：`run_logger.emit("run_end", decision=(locals().get("decision") or "Hold"))`。

- [ ] **Step 4: 实现 scheduler.py 传参**

在 `api/scheduler.py::_launch`（line 63）构造 runner 处加 `config`：

```python
        runner = AnalysisRunner(
            store=self._store(),
            event_queue=q,
            cancel_event=cancel_event,
            telemetry=telemetry,
            config=getattr(graph, "config", None) or {},
        )
```

> `graph.config` 是 `real_graph_factory` 里传给 `TradingAgentsGraph` 的合并配置（含 `log_*` 键，因 `DEFAULT_CONFIG.copy()`）。

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_runner_logging.py -v`
Expected: PASS（1 passed）
Run: `.venv/bin/python -m pytest tests/webui/test_runner.py -v` 确认现有 runner 测试不回归（若失败，多半是 `AnalysisRunner` 新增关键字参数——它有默认值，应兼容）。
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add api/runner.py api/scheduler.py tests/webui/test_runner_logging.py
git commit -m "feat(webui): stream log events and write run log file in runner"
```

---

## Task 10: 回读接口 GET /{run_id}/logs

**Files:**
- Modify: `api/routes/analysis.py`
- Test: `tests/webui/test_logs_route.py`（追加路由用例）

**Interfaces:**
- Consumes: `Store.get_log_path`（Task 8）
- Produces: `GET /api/analysis/{run_id}/logs` → `{"run_id": str, "events": list[dict]}`；文件缺失 → 404。

- [ ] **Step 1: 写失败测试**（追加到 `tests/webui/test_logs_route.py`）

```python
from fastapi.testclient import TestClient


def test_logs_route_returns_events(tmp_path, monkeypatch):
    import api.main as main

    store = Store(tmp_path / "webui.db")
    monkeypatch.setattr(main, "get_store", lambda: store)

    store.enqueue_run(run_id="r1", ticker="SPY", trade_date="2026-07-03",
                      asset_type="stock", config={})
    log_file = tmp_path / "SPY_1.jsonl"
    log_file.write_text('{"seq":1,"event_type":"run_start"}\n{"seq":2,"event_type":"run_end"}\n',
                        encoding="utf-8")
    store.set_log_path("r1", str(log_file))

    client = TestClient(main.app)
    resp = client.get("/api/analysis/r1/logs")
    assert resp.status_code == 200
    body = resp.json()
    assert [e["event_type"] for e in body["events"]] == ["run_start", "run_end"]


def test_logs_route_404_when_missing(tmp_path, monkeypatch):
    import api.main as main

    store = Store(tmp_path / "webui.db")
    monkeypatch.setattr(main, "get_store", lambda: store)
    client = TestClient(main.app)
    assert client.get("/api/analysis/unknown/logs").status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_logs_route.py -v -k route`
Expected: FAIL（404 vs 200 / 路由不存在返回 404 但结构不符）

- [ ] **Step 3: 实现路由**

在 `api/routes/analysis.py` 末尾（其它 `@router.get` 之后）加：

```python
@router.get("/{run_id}/logs")
def analysis_logs(run_id: str) -> dict:
    import json
    from pathlib import Path

    from api.main import get_store

    store = get_store()
    path = store.get_log_path(run_id)
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="logs not found")

    events: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return {"run_id": run_id, "events": events}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_logs_route.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add api/routes/analysis.py tests/webui/test_logs_route.py
git commit -m "feat(webui): add GET /api/analysis/{run_id}/logs replay endpoint"
```

---

## Task 11: 前端日志面板（实时流 + 过滤/搜索/展开）

**Files:**
- Modify: `webui/lib/sse.ts`（订阅 `log` 事件）
- Modify: `webui/lib/types.ts`（`SSEEvent` 加 `log` 变体；新增 `LogEvent` 类型）
- Modify: `webui/lib/api.ts`（`getRunLogs(runId)`）
- Create: `webui/lib/logs.ts` + `webui/lib/logs.test.ts`（`filterLogs` 纯函数 + vitest）
- Create: `webui/components/LogPanel.tsx`
- Modify: `webui/app/page.tsx`（logs state + `log` 事件处理 + 挂载 `LogPanel`）

**先决**：阅读 `webui/node_modules/next/dist/docs/`（相关 client component / hooks 部分）后再写 `.tsx`。

**Interfaces:**
- Consumes: `GET /api/analysis/{run_id}/logs`（Task 10）；SSE `log` 事件（Task 9）
- Produces:
  - `LogEvent = { ts: string; seq: number; run_id: string; event_type: string; [k: string]: unknown }`
  - `filterLogs(logs: LogEvent[], opts: { types: string[]; query: string }): LogEvent[]`
  - `getRunLogs(runId: string): Promise<LogEvent[]>`
  - `<LogPanel logs={LogEvent[]} />`

- [ ] **Step 1: 写 filterLogs 失败测试**

Create `webui/lib/logs.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { filterLogs, type LogEvent } from "./logs";

const logs: LogEvent[] = [
  { ts: "t", seq: 1, run_id: "r", event_type: "llm_call", model: "gpt" },
  { ts: "t", seq: 2, run_id: "r", event_type: "vendor_call", method: "get_news" },
  { ts: "t", seq: 3, run_id: "r", event_type: "node_enter", node: "Trader" },
];

describe("filterLogs", () => {
  it("returns all when no type filter and empty query", () => {
    expect(filterLogs(logs, { types: [], query: "" })).toHaveLength(3);
  });
  it("filters by event type", () => {
    const out = filterLogs(logs, { types: ["vendor_call"], query: "" });
    expect(out.map((l) => l.seq)).toEqual([2]);
  });
  it("filters by case-insensitive substring across payload", () => {
    expect(filterLogs(logs, { types: [], query: "trader" }).map((l) => l.seq)).toEqual([3]);
    expect(filterLogs(logs, { types: [], query: "GPT" }).map((l) => l.seq)).toEqual([1]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd webui && npx vitest run lib/logs.test.ts`
Expected: FAIL（`Cannot find module './logs'`）

- [ ] **Step 3: 实现 logs.ts**

Create `webui/lib/logs.ts`:

```ts
export type LogEvent = {
  ts: string;
  seq: number;
  run_id: string;
  event_type: string;
  [key: string]: unknown;
};

export function filterLogs(
  logs: LogEvent[],
  opts: { types: string[]; query: string },
): LogEvent[] {
  const q = opts.query.trim().toLowerCase();
  return logs.filter((log) => {
    if (opts.types.length > 0 && !opts.types.includes(log.event_type)) return false;
    if (!q) return true;
    return JSON.stringify(log).toLowerCase().includes(q);
  });
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd webui && npx vitest run lib/logs.test.ts`
Expected: PASS（3 passed）

- [ ] **Step 5: 加 SSE + 类型 + api（无独立测试，随组件手测）**

在 `webui/lib/types.ts` 的 `SSEEvent` 联合类型（line 106 起）加一支：

```ts
  | { event: "log"; data: import("./logs").LogEvent }
```

在 `webui/lib/sse.ts` 的事件名数组（line 18–27）加 `"log"`：

```ts
      "debate_round",
      "log",
```

在 `webui/lib/api.ts` 末尾加：

```ts
import type { LogEvent } from "./logs";

export async function getRunLogs(runId: string): Promise<LogEvent[]> {
  const resp = await fetch(`${BASE}/api/analysis/${runId}/logs`);
  if (!resp.ok) return [];
  const body = await resp.json();
  return (body.events ?? []) as LogEvent[];
}
```

> `BASE` 常量在 `api.ts` 已有（`streamUrl` 使用它）。沿用同一常量。

- [ ] **Step 6: 实现 LogPanel.tsx**

Create `webui/components/LogPanel.tsx`（client component；配色随现有 Tailwind 约定，参考 `AgentProgress.tsx` / `MessageBubble.tsx`）:

```tsx
"use client";

import { useMemo, useRef, useState } from "react";
import { filterLogs, type LogEvent } from "@/lib/logs";

const TYPE_COLORS: Record<string, string> = {
  run_start: "text-emerald-600",
  run_end: "text-emerald-700",
  node_enter: "text-slate-500",
  node_exit: "text-slate-400",
  llm_call: "text-violet-600",
  tool_call: "text-indigo-600",
  vendor_call: "text-blue-600",
  debate_round: "text-amber-600",
  report_section: "text-teal-600",
  memory_op: "text-fuchsia-600",
  checkpoint_op: "text-cyan-600",
  error: "text-red-600",
};

export function LogPanel({ logs }: { logs: LogEvent[] }) {
  const [types, setTypes] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const allTypes = useMemo(
    () => Array.from(new Set(logs.map((l) => l.event_type))).sort(),
    [logs],
  );
  const shown = useMemo(() => filterLogs(logs, { types, query }), [logs, types, query]);

  const toggleType = (t: string) =>
    setTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <button
        className="flex w-full items-center justify-between px-4 py-2 text-sm font-medium"
        onClick={() => setOpen((o) => !o)}
      >
        <span>详细日志 ({logs.length})</span>
        <span>{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="border-t border-slate-100 p-3">
          <div className="mb-2 flex flex-wrap gap-1">
            {allTypes.map((t) => (
              <button
                key={t}
                onClick={() => toggleType(t)}
                className={`rounded px-2 py-0.5 text-xs ${
                  types.includes(t) ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-600"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索日志…"
            className="mb-2 w-full rounded border border-slate-200 px-2 py-1 text-sm"
          />
          <div ref={scrollRef} className="max-h-96 overflow-auto font-mono text-xs">
            {shown.map((log) => (
              <div key={log.seq} className="border-b border-slate-50 py-1">
                <button
                  className="flex w-full gap-2 text-left"
                  onClick={() => setExpanded(expanded === log.seq ? null : log.seq)}
                >
                  <span className="text-slate-400">{log.seq}</span>
                  <span className={TYPE_COLORS[log.event_type] ?? "text-slate-700"}>
                    {log.event_type}
                  </span>
                  <span className="truncate text-slate-500">
                    {log.node ?? log.model ?? log.method ?? log.section ?? ""}
                  </span>
                </button>
                {expanded === log.seq && (
                  <pre className="mt-1 whitespace-pre-wrap break-all rounded bg-slate-50 p-2 text-slate-700">
                    {JSON.stringify(log, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
```

> 若 `@/` 别名未配置，用相对路径 `../lib/logs`。参考 `webui/components/*` 现有 import 风格确定。

- [ ] **Step 7: 接入 page.tsx**

在 `webui/app/page.tsx`：
1. import：`import { LogPanel } from "@/components/LogPanel";`、`import { getRunLogs } from "@/lib/api";`、`import type { LogEvent } from "@/lib/logs";`
2. 加 state：`const [logs, setLogs] = useState<LogEvent[]>([]);`
3. 在 `subscribe` 的 `onEvent`（line ~500）里加分支：
   ```tsx
   else if (e.event === "log") {
     setLogs((prev) => [...prev, e.data]);
   }
   ```
4. 开始新 run 时清空：在触发订阅前 `setLogs([])`。
5. 查看历史/刷新恢复某个已完成 run 时：`getRunLogs(runId).then(setLogs)`（放在现有加载历史详情的位置，与 `runtimeStatus` 回填同处）。
6. 在结果区渲染：`<LogPanel logs={logs} />`（放在 `AgentProgress` / 报告区附近）。

> 具体插入点以现有 `app/page.tsx` 的 run 生命周期 effect 为准；模式对齐现有 `report_section` / `debate_round` 的处理方式。

- [ ] **Step 8: 验证**

Run: `cd webui && npx vitest run lib/logs.test.ts`（3 passed）
Run: `cd webui && npx tsc --noEmit`（类型检查通过）
手测：`./dev.sh` 起服务，发起一次分析，确认日志面板实时逐行出现、着色正确、过滤/搜索/展开可用；刷新页面后 `/logs` 回读历史。

- [ ] **Step 9: 提交**

```bash
git add webui/lib/logs.ts webui/lib/logs.test.ts webui/lib/sse.ts webui/lib/types.ts webui/lib/api.ts webui/components/LogPanel.tsx webui/app/page.tsx
git commit -m "feat(webui): live log panel with filter/search/expand + /logs replay"
```

---

## Task 12: 收尾 — CHANGELOG + 全量验证

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 更新 CHANGELOG.md**

在 `## [Unreleased]` 的 `### Added` 下追加（无该小节则新建）:

```markdown
- 详细分析日志：每次分析写一份 JSONL（`~/.tradingagents/run_logs/<TICKER>_<时间戳>_<run8>.jsonl`），
  记录 run/node/llm/tool/vendor/debate/report/memory/checkpoint/error 事件；Web UI 实时查看
  （SSE `log` 事件）+ `GET /api/analysis/{run_id}/logs` 回读。可用 `TRADINGAGENTS_LOG_ENABLED`
  / `TRADINGAGENTS_LOG_DIR` / `TRADINGAGENTS_LOG_TRUNCATE_CHARS` 配置。
```

- [ ] **Step 2: 全量 lint + 测试**

Run: `.venv/bin/python -m ruff check .`
Expected: 无新增错误
Run: `.venv/bin/python -m pytest -m "not integration"`
Expected: 全绿（含新增 `tests/obs/` 与 `tests/webui/` 用例）
Run: `cd webui && npx vitest run && npx tsc --noEmit`
Expected: 全绿

- [ ] **Step 3: 提交**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for detailed analysis logging"
```

---

## Self-Review（已执行）

- **Spec 覆盖**：范围 B（Task 3/4/5/6/7=核心埋点覆盖全入口 + Task 9=WebUI）✓；JSONL（Task 1）✓；SSE+文件回读组合（Task 9 sink + Task 10 /logs + Task 11 前端）✓；LLM 完整截断（Task 3 + `truncate`）✓；全事件类型含 memory/checkpoint（Task 3/4/5/6）✓；文件命名（Task 2 `build_log_path`）✓；UI 进阶查看器（Task 11 过滤/搜索/展开）✓；ContextVar 埋点（Task 1）✓；配置+脱敏（Task 2 + `redact`）✓。
- **占位符扫描**：无 TBD/TODO；每个代码步骤含完整代码。
- **类型一致性**：`create_run_logger`/`RunLogger`/`get_current_run_logger`/`wrap_node`/`ObsCallbackHandler`/`filterLogs`/`LogEvent`/`getRunLogs`/`set_log_path`/`get_log_path` 在定义与消费任务间签名一致。
- **偏离记录**：日志目录用 `run_logs/`（非 spec 的 `logs/`，因 `results_dir` 已占用），已在 Global Constraints 与 Task 2 标注。
- **已知限制**：WebUI 路径下，`get_past_context` 等在请求线程（factory）中先于 runner 线程执行的 memory 读操作不在 logger 上下文内，不会记录 `memory_op inject`——这是既有执行结构决定的，不扩大范围去改。
