# Watchlist 批量分析 TUI 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `tradingagents batch` 子命令：读 webUI 的 watchlist，按顺序把每个标的入队跑完整分析，结果写进同一个 `webui.db`，webUI 历史页可见；终端用 rich `Live` 看板显示批次进度。

**Architecture:** TUI 是 API 服务的瘦 HTTP 客户端（复用现有 scheduler/runner/store）。`cli/api_client.py` 封装 REST 调用；`cli/batch_dashboard.py` 是纯状态机 + rich 渲染；`cli/batch.py` 做编排（探活→交互选设置→逐个入队→轮询看板→汇总）；`cli/main.py` 注册命令。当前 run 详情用**轮询** `GET /api/analysis/{run_id}/status`，不订阅 SSE。

**Tech Stack:** Python 3.10+、Typer、rich、questionary（均已在用）、`requests`（已是运行时依赖）。**不新增任何依赖。**

## Global Constraints

- 所有 Python/pytest 命令用 `.venv/bin/python`（系统 python 可能是 3.9，会崩）。
- 不新增依赖：HTTP 用 `requests`（已装）；不引入 `sseclient`/`responses`。
- 复用现有 `cli/utils.py` 选择器与 `cli/models.py` 枚举，不重复实现。
- **不改动** `api/`、`tradingagents/`、`webui/`——只新增 `cli/` 文件 + 在 `cli/main.py` 注册命令。
- 测试标记用 `unit`（`--strict-markers` 已开）；`conftest.py` autouse 注入 placeholder key。
- 收尾手动跑 `.venv/bin/python -m ruff check .` 和 `.venv/bin/python -m pytest -m "not integration"`。
- 提交用 Conventional Commits（`feat(cli):` / `test(cli):`），同步维护 `CHANGELOG.md`（Keep a Changelog）。仅在用户明确要求时提交。
- 与用户对话一律中文。

### 关键接口事实（已核对代码，勿臆测）

- `EnqueueRequest`（[api/schemas.py:34-65](../../../api/schemas.py#L34-L65)）字段：`tickers: list[str]`、`ticker_names: dict[str,str]`、`trade_date: str`、`asset_type: "stock"|"crypto"`、`analysts: list["market"|"social"|"news"|"fundamentals"]`、`research_depth: 1|3|5`、`output_language: str`、`llm_provider/deep_think_llm/quick_think_llm: str|None`。校验器把 `tickers` 做 `strip().upper()` + 去重（不重排）。
- `POST /api/queue`（[api/routes/queue.py:12-38](../../../api/routes/queue.py#L12-L38)）返回 `{"run_ids": [...], "running_run_id": str|None, "queue": {...}}`，`run_ids` 顺序对应规范化后的 `tickers`。`ticker_names` 的 key 必须是规范化（upper）后的 ticker。
- `GET /api/queue` → `QueueState`：`{"running": QueueItem|None, "pending": [QueueItem]}`，`QueueItem = {run_id, ticker, status, queue_position, created_at}`。
- `GET /api/analysis/{run_id}/status`（[api/routes/analysis.py:63-94](../../../api/routes/analysis.py#L63-L94)）：run_id 不存在→404；否则返回 telemetry 快照含 `db_status`、`llm_active`、`active_llm_calls`、`last_llm_model`、`last_llm_error`、`last_report_section`、`last_report_at` 等。
- `GET /api/history`（`list_runs`，[api/store.py:227-245](../../../api/store.py#L227-L245)）→ `list[HistorySummary]`：`{run_id, ticker, trade_date, decision, status, created_at, instrument_name}`，**排除 pending**、含 running/completed/error/cancelled。
- `GET /api/watchlist` → `list[{ticker, name}]`（按 position 排序）。
- 选择器返回值：`select_analysts()`→`list[AnalystType]`（`.value` = "market"/"social"/"news"/"fundamentals"）；`select_llm_provider()`→`(provider_key: str, url: str|None)`；`select_deep_thinking_agent(provider)`/`select_shallow_thinking_agent(provider)`→`str`；`select_research_depth()`→`int(1|3|5)`；`ask_output_language()`→`str`；`get_analysis_date()`→`str`；`detect_asset_type(ticker)`→`AssetType`（`.value` = "stock"/"crypto"）。
- 报告章节 key（[api/runner.py:12-21](../../../api/runner.py#L12-L21)）：`market_report, sentiment_report, news_report, fundamentals_report, investment_plan, trader_investment_plan, final_trade_decision, validation_report`。

---

## File Structure

- **Create `cli/api_client.py`** — `ApiError` + `ApiClient`（HTTP 封装：get_watchlist / enqueue / get_queue / get_status / get_history）。唯一碰 `requests` 的地方。
- **Create `cli/batch_dashboard.py`** — `TickerRow` + `BatchState` 纯状态机 + rich 渲染。无 HTTP、无 IO。
- **Create `cli/batch.py`** — `BatchSettings` + `collect_settings()`（交互）+ `analysts_for_asset_type()` + `enqueue_watchlist()` + `poll_until_done()` + `run_batch()`（编排）。
- **Modify `cli/main.py`** — 新增 `@app.command("batch")`，转调 `cli.batch.run_batch`。
- **Create `tests/cli/test_api_client.py`**、**`tests/cli/test_batch_dashboard.py`**、**`tests/cli/test_batch.py`** — 单元测试。

---

## Task 1: `cli/api_client.py` —— REST 客户端

**Files:**
- Create: `cli/api_client.py`
- Test: `tests/cli/test_api_client.py`

**Interfaces:**
- Produces:
  - `class ApiError(Exception)`
  - `ApiClient(base_url: str | None = None, timeout: float = 30.0)`，属性 `.base_url`（已去尾斜杠）
  - `ApiClient.get_watchlist() -> list[dict]`
  - `ApiClient.enqueue(*, ticker: str, name: str, trade_date: str, asset_type: str, analysts: list[str], research_depth: int, output_language: str, llm_provider: str | None, deep_think_llm: str | None, quick_think_llm: str | None) -> dict`
  - `ApiClient.get_queue() -> dict`
  - `ApiClient.get_status(run_id: str) -> dict | None`（网络错误/404 返回 `None`）
  - `ApiClient.get_history() -> list[dict]`
- base_url 解析优先级：构造参数 > `TRADINGAGENTS_API_URL` 环境变量 > `http://localhost:8000`。

- [ ] **Step 1: 写失败测试 — base_url 解析**

创建 `tests/cli/test_api_client.py`：

```python
import json

import pytest

from cli.api_client import ApiClient, ApiError


@pytest.mark.unit
def test_base_url_precedence_arg_over_env(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_API_URL", "http://env-host:9000")
    client = ApiClient("http://arg-host:8000/")
    assert client.base_url == "http://arg-host:8000"  # trailing slash stripped


@pytest.mark.unit
def test_base_url_from_env(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_API_URL", "http://env-host:9000/")
    assert ApiClient().base_url == "http://env-host:9000"


@pytest.mark.unit
def test_base_url_default(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_API_URL", raising=False)
    assert ApiClient().base_url == "http://localhost:8000"
```

- [ ] **Step 2: 运行验证失败**

Run: `.venv/bin/python -m pytest tests/cli/test_api_client.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'cli.api_client'`）

- [ ] **Step 3: 写 `cli/api_client.py`**

```python
"""Thin HTTP client for the TradingAgents WebUI API (used by the batch TUI)."""

import os

import requests

DEFAULT_BASE_URL = "http://localhost:8000"


class ApiError(Exception):
    """Any failure talking to the WebUI API (network error or non-2xx)."""


class ApiClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        resolved = base_url or os.getenv("TRADINGAGENTS_API_URL") or DEFAULT_BASE_URL
        self.base_url = resolved.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str):
        try:
            resp = requests.get(f"{self.base_url}{path}", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise ApiError(f"GET {path} failed: {exc}") from exc

    def _post(self, path: str, payload: dict):
        try:
            resp = requests.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise ApiError(f"POST {path} failed: {exc}") from exc

    def get_watchlist(self) -> list[dict]:
        return self._get("/api/watchlist")

    def enqueue(
        self,
        *,
        ticker: str,
        name: str,
        trade_date: str,
        asset_type: str,
        analysts: list[str],
        research_depth: int,
        output_language: str,
        llm_provider: str | None,
        deep_think_llm: str | None,
        quick_think_llm: str | None,
    ) -> dict:
        normalized = ticker.strip().upper()
        payload = {
            "tickers": [normalized],
            "ticker_names": {normalized: name} if name else {},
            "trade_date": trade_date,
            "asset_type": asset_type,
            "analysts": analysts,
            "research_depth": research_depth,
            "output_language": output_language,
            "llm_provider": llm_provider,
            "deep_think_llm": deep_think_llm,
            "quick_think_llm": quick_think_llm,
        }
        return self._post("/api/queue", payload)

    def get_queue(self) -> dict:
        return self._get("/api/queue")

    def get_status(self, run_id: str) -> dict | None:
        try:
            return self._get(f"/api/analysis/{run_id}/status")
        except ApiError:
            return None

    def get_history(self) -> list[dict]:
        return self._get("/api/history")
```

- [ ] **Step 4: 运行 base_url 测试通过**

Run: `.venv/bin/python -m pytest tests/cli/test_api_client.py -v`
Expected: PASS（3 个 base_url 测试）

- [ ] **Step 5: 写请求行为测试（mock requests）**

追加到 `tests/cli/test_api_client.py`：

```python
from unittest.mock import MagicMock, patch


def _fake_response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


@pytest.mark.unit
def test_enqueue_builds_payload():
    client = ApiClient("http://h:8000")
    with patch("cli.api_client.requests.post") as post:
        post.return_value = _fake_response({"run_ids": ["r1"], "running_run_id": "r1"})
        out = client.enqueue(
            ticker="aapl", name="Apple", trade_date="2026-07-02", asset_type="stock",
            analysts=["market"], research_depth=3, output_language="Chinese",
            llm_provider="deepseek", deep_think_llm="deepseek-reasoner",
            quick_think_llm="deepseek-chat",
        )
    assert out["run_ids"] == ["r1"]
    url, kwargs = post.call_args[0][0], post.call_args[1]
    assert url == "http://h:8000/api/queue"
    body = kwargs["json"]
    assert body["tickers"] == ["AAPL"]              # normalized upper
    assert body["ticker_names"] == {"AAPL": "Apple"}
    assert body["asset_type"] == "stock"


@pytest.mark.unit
def test_enqueue_omits_empty_name():
    client = ApiClient("http://h:8000")
    with patch("cli.api_client.requests.post") as post:
        post.return_value = _fake_response({"run_ids": ["r1"]})
        client.enqueue(
            ticker="BTC-USD", name="", trade_date="2026-07-02", asset_type="crypto",
            analysts=["market"], research_depth=1, output_language="English",
            llm_provider=None, deep_think_llm=None, quick_think_llm=None,
        )
    assert post.call_args[1]["json"]["ticker_names"] == {}


@pytest.mark.unit
def test_get_status_swallows_error_returns_none():
    client = ApiClient("http://h:8000")
    with patch("cli.api_client.requests.get") as get:
        get.side_effect = requests.RequestException("404")
        assert client.get_status("missing") is None


@pytest.mark.unit
def test_get_watchlist_wraps_network_error():
    client = ApiClient("http://h:8000")
    with patch("cli.api_client.requests.get") as get:
        get.side_effect = requests.ConnectionError("refused")
        with pytest.raises(ApiError):
            client.get_watchlist()
```

顶部补充 `import requests`（测试里用到异常类型）。

- [ ] **Step 6: 运行全部通过**

Run: `.venv/bin/python -m pytest tests/cli/test_api_client.py -v`
Expected: PASS（全部 7 个）

- [ ] **Step 7: 提交**

```bash
git add cli/api_client.py tests/cli/test_api_client.py
git commit -m "feat(cli): add WebUI API client for batch TUI"
```

---

## Task 2: `cli/batch_dashboard.py` —— 看板状态机

**Files:**
- Create: `cli/batch_dashboard.py`
- Test: `tests/cli/test_batch_dashboard.py`

**Interfaces:**
- Consumes: 无（纯数据结构，接收 dict 快照）。
- Produces:
  - `class TickerRow`（dataclass）：`ticker: str, name: str, run_id: str | None = None, status: str = "pending", decision: str | None = None`
  - `class BatchState`：
    - `__init__(self, watchlist: list[dict])`
    - `set_run_map(self, run_map: dict[str, str])`（run_id → 规范化 ticker）
    - `mark_error(self, ticker: str)`（ticker 已规范化 upper）
    - `apply_queue(self, queue: dict)`（设置 running/pending，更新 `self.current_running_id`）
    - `apply_history(self, history: list[dict])`（用 run_id 补终态 + decision）
    - `apply_status(self, status: dict | None)`（存当前 run 详情）
    - `all_done(self) -> bool`
    - `render(self)`（返回 rich renderable）
  - `SECTION_LABELS: dict[str, str]`、`STATUS_ICONS: dict[str, str]`

- [ ] **Step 1: 写失败测试 — 初始化 + set_run_map + all_done**

创建 `tests/cli/test_batch_dashboard.py`：

```python
import pytest

from cli.batch_dashboard import BatchState


def _state():
    return BatchState([{"ticker": "AAPL", "name": "Apple"}, {"ticker": "btc-usd", "name": ""}])


@pytest.mark.unit
def test_init_normalizes_ticker_and_defaults_pending():
    s = _state()
    assert [r.ticker for r in s.rows] == ["AAPL", "BTC-USD"]
    assert all(r.status == "pending" for r in s.rows)
    assert not s.all_done()


@pytest.mark.unit
def test_set_run_map_links_run_ids():
    s = _state()
    s.set_run_map({"r1": "AAPL", "r2": "BTC-USD"})
    assert s.rows[0].run_id == "r1"
    assert s.rows[1].run_id == "r2"


@pytest.mark.unit
def test_mark_error_makes_row_terminal():
    s = _state()
    s.mark_error("AAPL")
    s.mark_error("BTC-USD")
    assert s.all_done()
```

- [ ] **Step 2: 运行验证失败**

Run: `.venv/bin/python -m pytest tests/cli/test_batch_dashboard.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'cli.batch_dashboard'`）

- [ ] **Step 3: 写 `cli/batch_dashboard.py`（数据结构 + 状态方法）**

```python
"""State machine + rich rendering for the batch analysis dashboard."""

from dataclasses import dataclass

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

STATUS_ICONS = {
    "pending": "⏳",
    "running": "▶",
    "completed": "✓",
    "error": "✗",
    "cancelled": "⊘",
}

# report section key -> Chinese label (keys mirror api/runner.py REPORT_SECTIONS)
SECTION_LABELS = {
    "market_report": "市场分析",
    "sentiment_report": "情绪分析",
    "news_report": "新闻分析",
    "fundamentals_report": "基本面分析",
    "investment_plan": "研究经理复盘",
    "trader_investment_plan": "交易员计划",
    "final_trade_decision": "组合经理决策",
    "validation_report": "报告校验",
}

_TERMINAL = ("completed", "error", "cancelled")


@dataclass
class TickerRow:
    ticker: str
    name: str
    run_id: str | None = None
    status: str = "pending"
    decision: str | None = None


class BatchState:
    def __init__(self, watchlist: list[dict]):
        self.rows: list[TickerRow] = [
            TickerRow(ticker=item["ticker"].strip().upper(), name=item.get("name") or "")
            for item in watchlist
        ]
        self._by_ticker: dict[str, TickerRow] = {r.ticker: r for r in self.rows}
        self._by_run: dict[str, TickerRow] = {}
        self.current_running_id: str | None = None
        self.current_detail: dict | None = None

    def set_run_map(self, run_map: dict[str, str]) -> None:
        for run_id, ticker in run_map.items():
            row = self._by_ticker.get(ticker)
            if row is not None:
                row.run_id = run_id
                self._by_run[run_id] = row

    def mark_error(self, ticker: str) -> None:
        row = self._by_ticker.get(ticker)
        if row is not None:
            row.status = "error"

    def apply_queue(self, queue: dict) -> None:
        running = queue.get("running")
        pending_ids = {p["run_id"] for p in queue.get("pending", [])}
        self.current_running_id = running["run_id"] if running else None
        for row in self.rows:
            if row.run_id is None:
                continue
            if running and row.run_id == running["run_id"]:
                row.status = "running"
            elif row.run_id in pending_ids:
                row.status = "pending"
            # else: terminal — leave for apply_history to confirm

    def apply_history(self, history: list[dict]) -> None:
        for entry in history:
            row = self._by_run.get(entry["run_id"])
            if row is None:
                continue
            row.status = entry["status"]
            if entry.get("decision"):
                row.decision = entry["decision"]

    def apply_status(self, status: dict | None) -> None:
        self.current_detail = status

    def all_done(self) -> bool:
        return all(row.status in _TERMINAL for row in self.rows)
```

- [ ] **Step 4: 运行 Step 1 的三个测试通过**

Run: `.venv/bin/python -m pytest tests/cli/test_batch_dashboard.py -v`
Expected: PASS（3 个）

- [ ] **Step 5: 写状态转移测试（queue / history）**

追加：

```python
@pytest.mark.unit
def test_apply_queue_sets_running_and_pending():
    s = _state()
    s.set_run_map({"r1": "AAPL", "r2": "BTC-USD"})
    s.apply_queue({
        "running": {"run_id": "r1", "ticker": "AAPL", "status": "running",
                    "queue_position": None, "created_at": "t"},
        "pending": [{"run_id": "r2", "ticker": "BTC-USD", "status": "pending",
                     "queue_position": 1, "created_at": "t"}],
    })
    assert s.current_running_id == "r1"
    assert s.rows[0].status == "running"
    assert s.rows[1].status == "pending"
    assert not s.all_done()


@pytest.mark.unit
def test_apply_history_fills_decision_and_terminal():
    s = _state()
    s.set_run_map({"r1": "AAPL", "r2": "BTC-USD"})
    s.apply_history([
        {"run_id": "r1", "ticker": "AAPL", "trade_date": "2026-07-02",
         "decision": "Buy", "status": "completed", "created_at": "t",
         "instrument_name": "Apple"},
        {"run_id": "r2", "ticker": "BTC-USD", "trade_date": "2026-07-02",
         "decision": None, "status": "error", "created_at": "t",
         "instrument_name": None},
    ])
    assert s.rows[0].status == "completed"
    assert s.rows[0].decision == "Buy"
    assert s.rows[1].status == "error"
    assert s.all_done()


@pytest.mark.unit
def test_apply_queue_ignores_unlinked_rows():
    s = _state()  # no run_map set
    s.apply_queue({"running": None, "pending": []})
    assert s.current_running_id is None
    assert all(r.status == "pending" for r in s.rows)
```

- [ ] **Step 6: 运行通过**

Run: `.venv/bin/python -m pytest tests/cli/test_batch_dashboard.py -v`
Expected: PASS（6 个）

- [ ] **Step 7: 写 `render()`**

在 `BatchState` 末尾追加方法：

```python
    def _detail_panel(self) -> Panel:
        detail = self.current_detail
        if not self.current_running_id or not detail:
            return Panel(Text("暂无正在运行的分析", style="dim"), title="当前运行")
        row = self._by_run.get(self.current_running_id)
        header = f"{row.ticker} ({row.name})" if row and row.name else (row.ticker if row else "")
        section = detail.get("last_report_section")
        section_label = SECTION_LABELS.get(section, section) if section else "尚未产出章节"
        lines = [
            Text(header, style="bold"),
            Text(f"当前章节: {section_label}"),
            Text(
                f"LLM: {'活动中' if detail.get('llm_active') else '空闲'}"
                f" · 并发 {detail.get('active_llm_calls', 0)}"
                f" · 模型 {detail.get('last_llm_model') or '-'}"
            ),
        ]
        if detail.get("last_llm_error"):
            lines.append(Text(f"错误: {detail['last_llm_error']}", style="red"))
        return Panel(Group(*lines), title="当前运行")

    def render(self):
        table = Table(title="批量分析进度", expand=True)
        table.add_column("标的")
        table.add_column("状态", justify="center")
        table.add_column("决策", justify="center")
        for row in self.rows:
            label = f"{row.ticker}  {row.name}".strip()
            icon = STATUS_ICONS.get(row.status, "?")
            table.add_row(label, f"{icon} {row.status}", row.decision or "-")
        return Group(table, self._detail_panel())
```

- [ ] **Step 8: 写 render 冒烟测试**

追加：

```python
@pytest.mark.unit
def test_render_runs_without_error():
    from rich.console import Console

    s = _state()
    s.set_run_map({"r1": "AAPL"})
    s.apply_queue({"running": {"run_id": "r1", "ticker": "AAPL",
                               "status": "running", "queue_position": None,
                               "created_at": "t"}, "pending": []})
    s.apply_status({"last_report_section": "market_report", "llm_active": True,
                    "active_llm_calls": 1, "last_llm_model": "deepseek-chat",
                    "last_llm_error": None})
    Console(file=open("/dev/null", "w"), force_terminal=True).print(s.render())


@pytest.mark.unit
def test_render_no_running_shows_placeholder():
    from rich.console import Console

    s = _state()
    Console(file=open("/dev/null", "w"), force_terminal=True).print(s.render())
```

- [ ] **Step 9: 运行全部通过**

Run: `.venv/bin/python -m pytest tests/cli/test_batch_dashboard.py -v`
Expected: PASS（8 个）

- [ ] **Step 10: 提交**

```bash
git add cli/batch_dashboard.py tests/cli/test_batch_dashboard.py
git commit -m "feat(cli): add batch dashboard state machine and rendering"
```

---

## Task 3: `cli/batch.py` —— 编排逻辑（含入队 + 轮询循环）

**Files:**
- Create: `cli/batch.py`
- Test: `tests/cli/test_batch.py`

**Interfaces:**
- Consumes: `cli.api_client.ApiClient/ApiError`、`cli.batch_dashboard.BatchState`、`cli.utils` 选择器、`cli.models.AnalystType/AssetType`。
- Produces:
  - `@dataclass BatchSettings`：`analysts: list[str], research_depth: int, output_language: str, trade_date: str, llm_provider: str, deep_think_llm: str, quick_think_llm: str`
  - `analysts_for_asset_type(analysts: list[str], asset_type: str) -> list[str]`（crypto 去掉 fundamentals；若去空则回退原列表）
  - `collect_settings() -> BatchSettings`（交互，不做单元测试）
  - `enqueue_watchlist(client, watchlist: list[dict], settings: BatchSettings) -> tuple[dict[str, str], list[str]]`（返回 `(run_map run_id→upper ticker, failed upper tickers)`）
  - `poll_until_done(client, state: BatchState, poll_interval: float = 1.5, sleep=time.sleep, live=None) -> None`
  - `run_batch(api_url: str | None = None) -> None`（编排入口）

- [ ] **Step 1: 写失败测试 — analysts_for_asset_type**

创建 `tests/cli/test_batch.py`：

```python
import pytest

from cli.batch import analysts_for_asset_type


@pytest.mark.unit
def test_crypto_drops_fundamentals():
    assert analysts_for_asset_type(
        ["market", "social", "news", "fundamentals"], "crypto"
    ) == ["market", "social", "news"]


@pytest.mark.unit
def test_stock_keeps_all():
    assert analysts_for_asset_type(["market", "fundamentals"], "stock") == [
        "market", "fundamentals"
    ]


@pytest.mark.unit
def test_crypto_only_fundamentals_falls_back():
    # dropping would leave nothing -> keep original so server never 400s on empty
    assert analysts_for_asset_type(["fundamentals"], "crypto") == ["fundamentals"]
```

- [ ] **Step 2: 运行验证失败**

Run: `.venv/bin/python -m pytest tests/cli/test_batch.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'cli.batch'`）

- [ ] **Step 3: 写 `cli/batch.py`（骨架 + 纯函数 + 入队 + 轮询）**

```python
"""Batch analysis TUI: run the whole watchlist in order via the WebUI API."""

import time
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.live import Live

from cli.api_client import ApiClient, ApiError
from cli.batch_dashboard import BatchState
from cli.models import AssetType
from cli.utils import (
    ask_output_language,
    detect_asset_type,
    get_analysis_date,
    select_analysts,
    select_deep_thinking_agent,
    select_llm_provider,
    select_research_depth,
    select_shallow_thinking_agent,
)

console = Console()


@dataclass
class BatchSettings:
    analysts: list[str]
    research_depth: int
    output_language: str
    trade_date: str
    llm_provider: str
    deep_think_llm: str
    quick_think_llm: str


def analysts_for_asset_type(analysts: list[str], asset_type: str) -> list[str]:
    """Crypto has no fundamentals analyst; drop it, but never return empty."""
    if asset_type != "crypto":
        return analysts
    filtered = [a for a in analysts if a != "fundamentals"]
    return filtered or analysts


def collect_settings() -> BatchSettings:
    """Interactively gather one shared settings set for the whole batch."""
    provider, _url = select_llm_provider()
    deep = select_deep_thinking_agent(provider)
    quick = select_shallow_thinking_agent(provider)
    analysts = [a.value for a in select_analysts()]
    depth = select_research_depth()
    language = ask_output_language()
    trade_date = get_analysis_date()
    return BatchSettings(
        analysts=analysts,
        research_depth=depth,
        output_language=language,
        trade_date=trade_date,
        llm_provider=provider,
        deep_think_llm=deep,
        quick_think_llm=quick,
    )


def enqueue_watchlist(
    client: ApiClient, watchlist: list[dict], settings: BatchSettings
) -> tuple[dict[str, str], list[str]]:
    """Enqueue each ticker in order; return (run_id -> upper ticker, failed upper tickers)."""
    run_map: dict[str, str] = {}
    failed: list[str] = []
    for item in watchlist:
        ticker = item["ticker"]
        normalized = ticker.strip().upper()
        asset_type = detect_asset_type(ticker).value
        analysts = analysts_for_asset_type(settings.analysts, asset_type)
        try:
            resp = client.enqueue(
                ticker=ticker,
                name=item.get("name") or "",
                trade_date=settings.trade_date,
                asset_type=asset_type,
                analysts=analysts,
                research_depth=settings.research_depth,
                output_language=settings.output_language,
                llm_provider=settings.llm_provider,
                deep_think_llm=settings.deep_think_llm,
                quick_think_llm=settings.quick_think_llm,
            )
        except ApiError as exc:
            console.print(f"[red]入队失败 {normalized}: {exc}[/red]")
            failed.append(normalized)
            continue
        for run_id in resp.get("run_ids", []):
            run_map[run_id] = normalized
    return run_map, failed


def poll_until_done(
    client: ApiClient,
    state: BatchState,
    poll_interval: float = 1.5,
    sleep=time.sleep,
    live: Live | None = None,
) -> None:
    """Poll queue/history/status until every row is terminal."""
    while not state.all_done():
        try:
            state.apply_queue(client.get_queue())
            state.apply_history(client.get_history())
            if state.current_running_id:
                state.apply_status(client.get_status(state.current_running_id))
            else:
                state.apply_status(None)
        except ApiError:
            pass  # transient; keep last snapshot and retry next tick
        if live is not None:
            live.update(state.render())
        sleep(poll_interval)


def _print_summary(state: BatchState) -> None:
    console.print("\n[bold]批次汇总[/bold]")
    for row in state.rows:
        console.print(f"  {row.ticker}  {row.name}  ->  {row.status}  {row.decision or ''}")


def run_batch(api_url: str | None = None) -> None:
    client = ApiClient(api_url)
    try:
        watchlist = client.get_watchlist()
    except ApiError:
        console.print(
            "[red]无法连接 API 服务。[/red]请先启动：\n"
            "  ./dev.sh\n或\n"
            "  .venv/bin/python -m uvicorn api.main:app --port 8000"
        )
        raise typer.Exit(1)

    if not watchlist:
        console.print("[yellow]watchlist 为空。[/yellow]请先在 webUI 添加自选股。")
        raise typer.Exit(0)

    settings = collect_settings()
    run_map, failed = enqueue_watchlist(client, watchlist, settings)
    state = BatchState(watchlist)
    state.set_run_map(run_map)
    for ticker in failed:
        state.mark_error(ticker)

    try:
        with Live(state.render(), console=console, refresh_per_second=4) as live:
            poll_until_done(client, state, live=live)
            live.update(state.render())
    except KeyboardInterrupt:
        console.print("\n[yellow]已退出看板，队列仍在后台运行。[/yellow]")
        return
    _print_summary(state)
```

- [ ] **Step 4: 运行 analysts_for_asset_type 测试通过**

Run: `.venv/bin/python -m pytest tests/cli/test_batch.py -v`
Expected: PASS（3 个）

- [ ] **Step 5: 写 enqueue_watchlist 测试（fake client）**

追加到 `tests/cli/test_batch.py`：

```python
from cli.batch import BatchSettings, enqueue_watchlist, poll_until_done, run_batch
from cli.batch_dashboard import BatchState


class FakeClient:
    def __init__(self, *, watchlist=None, queues=None, history=None,
                 enqueue_side=None, status=None):
        self._watchlist = watchlist or []
        self._queues = list(queues or [])
        self._history = history or []
        self._enqueue_side = enqueue_side  # dict ticker->resp or Exception
        self._status = status
        self.enqueue_calls = []

    def get_watchlist(self):
        return self._watchlist

    def enqueue(self, *, ticker, **kwargs):
        self.enqueue_calls.append((ticker, kwargs))
        if isinstance(self._enqueue_side, dict):
            val = self._enqueue_side.get(ticker.strip().upper())
            if isinstance(val, Exception):
                raise val
            return val or {"run_ids": [f"run-{ticker.strip().upper()}"]}
        return {"run_ids": [f"run-{ticker.strip().upper()}"]}

    def get_queue(self):
        return self._queues.pop(0) if self._queues else {"running": None, "pending": []}

    def get_history(self):
        return self._history

    def get_status(self, run_id):
        return self._status


def _settings():
    return BatchSettings(
        analysts=["market", "fundamentals"], research_depth=3,
        output_language="Chinese", trade_date="2026-07-02",
        llm_provider="deepseek", deep_think_llm="deepseek-reasoner",
        quick_think_llm="deepseek-chat",
    )


@pytest.mark.unit
def test_enqueue_watchlist_preserves_order_and_maps_run_ids():
    client = FakeClient()
    wl = [{"ticker": "AAPL", "name": "Apple"},
          {"ticker": "BTC-USD", "name": ""},
          {"ticker": "MSFT", "name": "Microsoft"}]
    run_map, failed = enqueue_watchlist(client, wl, _settings())
    assert failed == []
    assert [c[0] for c in client.enqueue_calls] == ["AAPL", "BTC-USD", "MSFT"]
    assert run_map == {"run-AAPL": "AAPL", "run-BTC-USD": "BTC-USD", "run-MSFT": "MSFT"}


@pytest.mark.unit
def test_enqueue_watchlist_crypto_drops_fundamentals():
    client = FakeClient()
    enqueue_watchlist(client, [{"ticker": "BTC-USD", "name": ""}], _settings())
    _, kwargs = client.enqueue_calls[0]
    assert kwargs["analysts"] == ["market"]        # fundamentals dropped for crypto
    assert kwargs["asset_type"] == "crypto"


@pytest.mark.unit
def test_enqueue_watchlist_records_failures():
    client = FakeClient(enqueue_side={"AAPL": ApiError("boom")})
    run_map, failed = enqueue_watchlist(
        client, [{"ticker": "AAPL", "name": ""}], _settings()
    )
    assert failed == ["AAPL"]
    assert run_map == {}
```

（顶部补 `from cli.api_client import ApiError`。）

- [ ] **Step 6: 运行通过**

Run: `.venv/bin/python -m pytest tests/cli/test_batch.py -v`
Expected: PASS（6 个）

- [ ] **Step 7: 写 poll_until_done 测试**

追加：

```python
@pytest.mark.unit
def test_poll_until_done_advances_to_terminal():
    wl = [{"ticker": "AAPL", "name": "A"}, {"ticker": "MSFT", "name": "M"}]
    state = BatchState(wl)
    state.set_run_map({"run-AAPL": "AAPL", "run-MSFT": "MSFT"})
    queues = [
        {"running": {"run_id": "run-AAPL", "ticker": "AAPL", "status": "running",
                     "queue_position": None, "created_at": "t"},
         "pending": [{"run_id": "run-MSFT", "ticker": "MSFT", "status": "pending",
                      "queue_position": 1, "created_at": "t"}]},
        {"running": {"run_id": "run-MSFT", "ticker": "MSFT", "status": "running",
                     "queue_position": None, "created_at": "t"}, "pending": []},
        {"running": None, "pending": []},
    ]
    history = [
        {"run_id": "run-AAPL", "ticker": "AAPL", "trade_date": "t", "decision": "Buy",
         "status": "completed", "created_at": "t", "instrument_name": "A"},
        {"run_id": "run-MSFT", "ticker": "MSFT", "trade_date": "t", "decision": "Hold",
         "status": "completed", "created_at": "t", "instrument_name": "M"},
    ]
    client = FakeClient(queues=queues, history=history,
                        status={"last_report_section": "market_report"})
    poll_until_done(client, state, poll_interval=0, sleep=lambda _: None)
    assert state.all_done()
    assert state.rows[0].decision == "Buy"
    assert state.rows[1].decision == "Hold"


@pytest.mark.unit
def test_poll_until_done_survives_transient_api_error():
    state = BatchState([{"ticker": "AAPL", "name": "A"}])
    state.set_run_map({"run-AAPL": "AAPL"})

    class FlakyClient(FakeClient):
        def __init__(self):
            super().__init__(history=[
                {"run_id": "run-AAPL", "ticker": "AAPL", "trade_date": "t",
                 "decision": "Buy", "status": "completed", "created_at": "t",
                 "instrument_name": "A"}])
            self._first = True

        def get_queue(self):
            if self._first:
                self._first = False
                raise ApiError("transient")
            return {"running": None, "pending": []}

    poll_until_done(FlakyClient(), state, poll_interval=0, sleep=lambda _: None)
    assert state.all_done()
```

- [ ] **Step 8: 写 run_batch 守卫路径测试（探活失败 / 空 watchlist）**

追加：

```python
@pytest.mark.unit
def test_run_batch_exits_when_service_down(monkeypatch):
    def boom(self):
        raise ApiError("refused")
    monkeypatch.setattr("cli.batch.ApiClient.get_watchlist", boom)
    with pytest.raises(typer.Exit) as ei:
        run_batch()
    assert ei.value.exit_code == 1


@pytest.mark.unit
def test_run_batch_exits_when_watchlist_empty(monkeypatch):
    monkeypatch.setattr("cli.batch.ApiClient.get_watchlist", lambda self: [])
    with pytest.raises(typer.Exit) as ei:
        run_batch()
    assert ei.value.exit_code == 0
```

（顶部补 `import typer`。）

- [ ] **Step 9: 运行全部通过**

Run: `.venv/bin/python -m pytest tests/cli/test_batch.py -v`
Expected: PASS（10 个）

- [ ] **Step 10: 提交**

```bash
git add cli/batch.py tests/cli/test_batch.py
git commit -m "feat(cli): add batch orchestration (enqueue + poll loop)"
```

---

## Task 4: 注册 `tradingagents batch` 命令 + 冒烟测试

**Files:**
- Modify: `cli/main.py`（在 `analyze` 命令后新增 `batch` 命令）
- Test: `tests/cli/test_batch.py`（追加命令注册冒烟测试）

**Interfaces:**
- Consumes: `cli.batch.run_batch`。
- Produces: Typer 命令 `batch`，选项 `--api-url`。

- [ ] **Step 1: 写命令注册冒烟测试**

追加到 `tests/cli/test_batch.py`：

```python
@pytest.mark.unit
def test_batch_command_registered():
    from cli.main import app

    names = {cmd.name for cmd in app.registered_commands}
    assert "batch" in names
```

- [ ] **Step 2: 运行验证失败**

Run: `.venv/bin/python -m pytest tests/cli/test_batch.py::test_batch_command_registered -v`
Expected: FAIL（`assert "batch" in names` 失败——命令名集合里没有 `batch`）

- [ ] **Step 3: 在 `cli/main.py` 注册命令**

在 `analyze` 命令定义之后（`if __name__ == "__main__":` 之前）新增：

```python
@app.command("batch")
def batch(
    api_url: str = typer.Option(
        None,
        "--api-url",
        help="WebUI API base URL (default: $TRADINGAGENTS_API_URL or http://localhost:8000).",
    ),
):
    """按顺序批量分析 webUI 自选股，结果写入同一个历史库。"""
    from cli.batch import run_batch

    run_batch(api_url=api_url)
```

- [ ] **Step 4: 运行冒烟测试通过**

Run: `.venv/bin/python -m pytest tests/cli/test_batch.py::test_batch_command_registered -v`
Expected: PASS

- [ ] **Step 5: 跑全套 cli 测试**

Run: `.venv/bin/python -m pytest tests/cli/ -v`
Expected: PASS（全部 Task 1–4 用例）

- [ ] **Step 6: Lint**

Run: `.venv/bin/python -m ruff check cli/ tests/cli/`
Expected: 无错误（若有 import 排序/未用告警，按提示修）

- [ ] **Step 7: 更新 CHANGELOG.md**

在 `CHANGELOG.md` 的 `## [Unreleased]` → `### Added` 下加一行：

```markdown
- `tradingagents batch` 子命令：按顺序批量分析 webUI 自选股（watchlist），结果写入同一历史库，可在 webUI 查看。
```

（若无 `## [Unreleased]` 段落，参照文件现有格式新建。）

- [ ] **Step 8: 提交**

```bash
git add cli/main.py tests/cli/test_batch.py CHANGELOG.md
git commit -m "feat(cli): register tradingagents batch command"
```

---

## 最终验证

- [ ] **全量 lint + 测试**

Run:
```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -m "not integration" -q
```
Expected: lint 干净；测试全绿（新增 cli 用例 + 既有用例均通过）。

- [ ] **手动冒烟（可选，需真实服务 + key）**

启动服务（`./dev.sh` 或 uvicorn），在 webUI 加几个自选股，然后：
```bash
.venv/bin/python -m cli.main batch
```
交互选设置后应看到看板逐个推进，跑完的 run 在 webUI 历史页可见。

---

## 已知限制（记录，非本次目标）

- 选的 `llm_provider` 必须是服务端已配置 API key 的 provider，否则该 run 在服务端失败（与 webUI 行为一致——client 不传 key/backend_url，服务端用自己的 env 配置）。
- 看板不显示辩论轮次细粒度（那只在 SSE 里）；当前 run 详情来自 `/status` 的 `last_report_section` 等字段。
- 混合 stock/crypto 的 watchlist 严格按 watchlist 顺序跑（逐个入队保证）。
```

