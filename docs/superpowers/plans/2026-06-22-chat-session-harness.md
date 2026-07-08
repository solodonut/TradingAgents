# Chat 会话档案 Harness 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给投顾 Chat 加一层轻量"会话档案"机制——锚定用户确认过的关键参数（资金池等），并在缺参数或临时推断时强制先确认，杜绝反复算错。

**Architecture:** 复用现有 tool-call 循环 + `NO_DATA_AVAILABLE` 哨兵 + 持仓面板三大既有模式。新增会话级 `SessionProfile`（与 portfolio 平行存储），每轮注入 system prompt；新增两个 advisor 工具：`propose_session_facts`（对话抽取→前端确认卡片）和 `compute_position_sizing`（代码层硬约束 + 正确算术，缺资金池返回 `NEED_CONFIRMATION:` 哨兵）。前端新增参数面板与确认卡片。

**Tech Stack:** Python 3.10+ / FastAPI / SQLite / LangChain tools；Next.js 16 / React 19 / TypeScript；后端测试 pytest，前端测试 `node --test --experimental-strip-types`。

## Global Constraints

- Python 命令一律用 `.venv/bin/python`（如 `.venv/bin/python -m pytest ...`），不要用裸 `python3`/`pytest`。
- 后端 lint：`ruff check .`；E501 已忽略，不要因行长改动布局。
- 测试标记 `--strict-markers` 已开启；新单测不加 marker（默认即 unit），不得依赖网络或真实 key。
- advisor 层（`tradingagents/advisor/`）**不得** import `api.*`——保持 api→tradingagents 的单向依赖。profile 工具只接受普通 dict / 标量，不接受 `api.schemas` 的 pydantic 模型。
- 前端：动 `webui/` 代码前先读 `webui/node_modules/next/dist/docs/` 相关文档（见 `webui/AGENTS.md`）。
- 前端组件无单测惯例；前端测试只覆盖 `webui/lib/*.test.ts` 纯函数。
- 哨兵前缀统一：`NO_DATA_AVAILABLE:`、`DATA_SOURCE_DISABLED:`、新增 `NEED_CONFIRMATION:`。
- 提交规范 Conventional Commits；最终同步 `CHANGELOG.md`（Keep a Changelog）。
- 回复与代码注释里用户可见文案用中文。
- 风险偏好取值 `conservative|balanced|aggressive`；投资期限取值 `short|medium|long`。中文映射：保守/稳健/激进、短期/中期/长期。

---

## File Structure

新增：
- `tradingagents/advisor/profile_tools.py` — `propose_session_facts`、`compute_position_sizing` 两个工具的工厂。
- `tests/advisor/test_profile_tools.py` — 上述工具单测。
- `webui/components/chat/ProfilePanel.tsx` — 会话参数面板。
- `webui/components/chat/ProfileProposalCard.tsx` — 确认卡片。
- `webui/lib/chat-profile.ts` — 解析 `propose_session_facts` tool_call 的纯函数。
- `webui/lib/chat-profile.test.ts` — 上述纯函数测试。

修改：
- `api/schemas.py` — 新增 `SessionProfile`。
- `api/store.py` — `chat_profiles` 表 + `save_session_profile`/`get_session_profile` + 级联删除。
- `api/routes/chat.py` — profile 路由、`_profile_text`、`load_profile` 闭包、装配 profile 工具、注入 system prompt。
- `tradingagents/advisor/prompt.py` — 注入档案段 + 4 条新行为准则 + `build_system_prompt` 签名加 `profile_ctx`。
- `tradingagents/advisor/tools.py` — `NEED_CONFIRMATION:` 加入哨兵前缀。
- `webui/lib/types.ts` — `SessionProfile` 类型。
- `webui/lib/api.ts` — `getSessionProfile`/`saveSessionProfile`。
- `webui/lib/chat-export.ts` — 把 `propose_session_facts` 计入"内部工具"集合（不显示为数据来源）。
- `webui/components/chat/ChatMessage.tsx` — 渲染确认卡片。
- `webui/app/chat/page.tsx` — 装配面板、确认卡片回调、加载/保存 profile。
- `CHANGELOG.md`。

---

## Task 1: SessionProfile 数据模型

**Files:**
- Modify: `api/schemas.py`（在 `PortfolioHolding` 之后新增）
- Test: `tests/webui/test_chat_schemas.py`

**Interfaces:**
- Produces: `SessionProfile` pydantic 模型，字段：
  `available_capital: float | None`、`capital_currency: str = "CNY"`、
  `risk_tolerance: Literal["conservative","balanced","aggressive"] | None`、
  `max_single_position_pct: float | None`、
  `horizon: Literal["short","medium","long"] | None`、
  `constraints: str | None`、`confirmed_at: str | None`。

- [ ] **Step 1: 写失败测试**

在 `tests/webui/test_chat_schemas.py` 末尾追加：

```python
from api.schemas import SessionProfile


def test_session_profile_defaults_are_all_optional():
    profile = SessionProfile()
    assert profile.available_capital is None
    assert profile.capital_currency == "CNY"
    assert profile.risk_tolerance is None
    assert profile.max_single_position_pct is None
    assert profile.horizon is None
    assert profile.constraints is None
    assert profile.confirmed_at is None


def test_session_profile_accepts_full_values():
    profile = SessionProfile(
        available_capital=300000,
        capital_currency="USD",
        risk_tolerance="balanced",
        max_single_position_pct=25,
        horizon="medium",
        constraints="不碰白酒",
        confirmed_at="2026-06-22T00:00:00Z",
    )
    assert profile.available_capital == 300000
    assert profile.risk_tolerance == "balanced"
    assert profile.horizon == "medium"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_chat_schemas.py -q`
Expected: FAIL，`ImportError: cannot import name 'SessionProfile'`。

- [ ] **Step 3: 实现模型**

在 `api/schemas.py`（`PortfolioHolding` 类之后）新增：

```python
class SessionProfile(BaseModel):
    available_capital: float | None = None
    capital_currency: str = "CNY"
    risk_tolerance: Literal["conservative", "balanced", "aggressive"] | None = None
    max_single_position_pct: float | None = None
    horizon: Literal["short", "medium", "long"] | None = None
    constraints: str | None = None
    confirmed_at: str | None = None
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_chat_schemas.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add api/schemas.py tests/webui/test_chat_schemas.py
git commit -m "feat(chat): add SessionProfile schema"
```

---

## Task 2: Store 存取会话档案

**Files:**
- Modify: `api/store.py`（`_SCHEMA` 加表；`delete_chat_session` 加级联；末尾加方法）
- Test: `tests/webui/test_chat_store.py`

**Interfaces:**
- Consumes: `SessionProfile`（Task 1）。
- Produces:
  - `Store.save_session_profile(session_id: str, profile: SessionProfile) -> None`
  - `Store.get_session_profile(session_id: str) -> SessionProfile | None`（无记录返回 `None`）

- [ ] **Step 1: 写失败测试**

在 `tests/webui/test_chat_store.py` 末尾追加：

```python
from api.schemas import SessionProfile


def test_save_and_get_session_profile_overwrites(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title=None)
    store.save_session_profile("s1", SessionProfile(available_capital=100000))
    store.save_session_profile(
        "s1", SessionProfile(available_capital=300000, risk_tolerance="balanced")
    )
    profile = store.get_session_profile("s1")
    assert profile.available_capital == 300000
    assert profile.risk_tolerance == "balanced"


def test_get_session_profile_missing_returns_none(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title=None)
    assert store.get_session_profile("s1") is None


def test_delete_chat_session_cascades_profile(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title=None)
    store.save_session_profile("s1", SessionProfile(available_capital=100000))
    store.delete_chat_session("s1")
    assert store.get_session_profile("s1") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_chat_store.py -q`
Expected: FAIL，`AttributeError: 'Store' object has no attribute 'save_session_profile'`。

- [ ] **Step 3: 加表**

在 `api/store.py` 的 `_SCHEMA` 字符串末尾（`chat_portfolios` 表之后）追加：

```python
CREATE TABLE IF NOT EXISTS chat_profiles (
    session_id   TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
```

- [ ] **Step 4: 级联删除**

在 `api/store.py` 的 `delete_chat_session` 方法中，紧跟删除 `chat_portfolios` 那一行之后追加：

```python
            conn.execute("DELETE FROM chat_profiles WHERE session_id=?", (session_id,))
```

- [ ] **Step 5: 顶部导入 SessionProfile**

修改 `api/store.py` 顶部的 import：

```python
from api.schemas import (
    ChatMessage,
    ChatSession,
    HistorySummary,
    PortfolioHolding,
    RunResult,
    SessionProfile,
)
```

- [ ] **Step 6: 实现存取方法**

在 `api/store.py` 的 `get_portfolio` 方法之后（文件末尾）追加：

```python
    # ---- session profile ----

    def save_session_profile(self, session_id: str, profile: SessionProfile) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_profiles (session_id, profile_json, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "profile_json=excluded.profile_json, updated_at=excluded.updated_at",
                (session_id, _dumps(profile.model_dump()), _now()),
            )
            self._touch_session(conn, session_id)

    def get_session_profile(self, session_id: str) -> SessionProfile | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json FROM chat_profiles WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionProfile(**json.loads(row["profile_json"]))
```

- [ ] **Step 7: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_chat_store.py -q`
Expected: PASS。

- [ ] **Step 8: 提交**

```bash
git add api/store.py tests/webui/test_chat_store.py
git commit -m "feat(chat): persist session profile in store"
```

---

## Task 3: 会话档案路由 GET/PUT

**Files:**
- Modify: `api/routes/chat.py`（import 加 `SessionProfile`；在 `get_portfolio` 路由之后新增两条路由）
- Test: `tests/webui/test_routes_chat.py`

**Interfaces:**
- Consumes: `store.get_session_profile`/`save_session_profile`（Task 2）。
- Produces:
  - `GET /api/chat/sessions/{session_id}/profile` → `SessionProfile`（无记录返回全 `None` 的默认档案）。
  - `PUT /api/chat/sessions/{session_id}/profile`，请求体 `SessionProfile`，服务端写入前覆盖 `confirmed_at` 为当前时间，返回保存后的 `SessionProfile`。
  - 两者：session 不存在 → 404。

- [ ] **Step 1: 写失败测试**

在 `tests/webui/test_routes_chat.py` 末尾追加：

```python
def test_get_profile_defaults_when_unset(client):
    _install_fake_chat(client, [])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    resp = client.get(f"/api/chat/sessions/{sid}/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available_capital"] is None
    assert body["capital_currency"] == "CNY"


def test_put_profile_persists_and_sets_confirmed_at(client):
    _install_fake_chat(client, [])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    resp = client.put(
        f"/api/chat/sessions/{sid}/profile",
        json={"available_capital": 300000, "risk_tolerance": "balanced"},
    )
    assert resp.status_code == 200
    assert resp.json()["available_capital"] == 300000
    assert resp.json()["confirmed_at"] is not None
    # round-trips
    again = client.get(f"/api/chat/sessions/{sid}/profile").json()
    assert again["risk_tolerance"] == "balanced"


def test_profile_routes_404_for_missing_session(client):
    _install_fake_chat(client, [])
    assert client.get("/api/chat/sessions/nope/profile").status_code == 404
    assert (
        client.put("/api/chat/sessions/nope/profile", json={}).status_code == 404
    )
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_chat.py -k profile -q`
Expected: FAIL（404 处期望，但实为 405/404 路由不存在 → 断言失败）。

- [ ] **Step 3: import SessionProfile**

修改 `api/routes/chat.py` 顶部 `from api.schemas import (...)`，加入 `SessionProfile`：

```python
from api.schemas import (
    ChatRequest,
    ChatSessionBulkDelete,
    ChatSessionCreate,
    ChatSessionReportsUpdate,
    ChatSessionUpdate,
    PortfolioExtractResponse,
    PortfolioHolding,
    SessionProfile,
)
```

并在文件顶部已有的 `from datetime import ...` 处确认可用；若无，新增：

```python
from datetime import datetime, timezone
```

- [ ] **Step 4: 实现路由**

在 `api/routes/chat.py` 的 `get_portfolio` 路由函数之后新增：

```python
@router.get("/sessions/{session_id}/profile", response_model=SessionProfile)
def get_session_profile(session_id: str) -> SessionProfile:
    from api.main import get_store

    store = get_store()
    if store.get_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    return store.get_session_profile(session_id) or SessionProfile()


@router.put("/sessions/{session_id}/profile", response_model=SessionProfile)
def save_session_profile(
    session_id: str, payload: SessionProfile
) -> SessionProfile:
    from api.main import get_store

    store = get_store()
    if store.get_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    payload.confirmed_at = datetime.now(timezone.utc).isoformat()
    store.save_session_profile(session_id, payload)
    return payload
```

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_chat.py -k profile -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add api/routes/chat.py tests/webui/test_routes_chat.py
git commit -m "feat(chat): add session profile GET/PUT routes"
```

---

## Task 4: NEED_CONFIRMATION 哨兵

**Files:**
- Modify: `tradingagents/advisor/tools.py`
- Test: `tests/advisor/test_tools.py`

**Interfaces:**
- Produces: `is_no_data("NEED_CONFIRMATION: ...")` 返回 `True`。

- [ ] **Step 1: 写失败测试**

在 `tests/advisor/test_tools.py` 的 `test_is_no_data_detects_sentinels` 中追加一行断言：

```python
def test_is_no_data_detects_sentinels():
    assert is_no_data("NO_DATA_AVAILABLE: ticker not found")
    assert is_no_data("DATA_SOURCE_DISABLED: reddit off")
    assert is_no_data("NEED_CONFIRMATION: 缺少可用资金池")
    assert not is_no_data("AAPL,2024-01-01,190.0,...")
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/advisor/test_tools.py -q`
Expected: FAIL（`NEED_CONFIRMATION` 未被识别）。

- [ ] **Step 3: 加前缀**

修改 `tradingagents/advisor/tools.py` 的 `_NO_DATA_PREFIXES`：

```python
_NO_DATA_PREFIXES = (
    "NO_DATA_AVAILABLE:",
    "DATA_SOURCE_DISABLED:",
    "NEED_CONFIRMATION:",
)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/advisor/test_tools.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add tradingagents/advisor/tools.py tests/advisor/test_tools.py
git commit -m "feat(advisor): recognize NEED_CONFIRMATION sentinel"
```

---

## Task 5: propose_session_facts 工具

**Files:**
- Create: `tradingagents/advisor/profile_tools.py`
- Test: `tests/advisor/test_profile_tools.py`

**Interfaces:**
- Produces:
  - `create_profile_tools(*, load_profile: Callable[[], dict]) -> list[BaseTool]`
    返回 `[propose_session_facts, compute_position_sizing]`（本任务先实现前者，Task 6 补后者）。
  - `propose_session_facts(available_capital=None, capital_currency=None, risk_tolerance=None, max_single_position_pct=None, horizon=None, constraints=None) -> str`
    返回 JSON 字符串：`{"proposal": {<仅含非 None 字段>}, "instruction": "..."}`。
    校验失败抛 `ValueError`；未提供任何字段抛 `ValueError`。
- Consumes: `load_profile`（本任务的工厂参数；propose 工具不读它，但与 Task 6 共用工厂）。

- [ ] **Step 1: 写失败测试**

创建 `tests/advisor/test_profile_tools.py`：

```python
import json

import pytest

from tradingagents.advisor.profile_tools import create_profile_tools


def _tools(profile: dict | None = None):
    state = {"profile": profile or {}}
    tools = create_profile_tools(load_profile=lambda: state["profile"])
    return {t.name: t for t in tools}, state


def test_propose_session_facts_returns_only_provided_fields():
    tools, _ = _tools()
    out = tools["propose_session_facts"].invoke(
        {"available_capital": 300000, "capital_currency": "CNY"}
    )
    payload = json.loads(out)
    assert payload["proposal"] == {
        "available_capital": 300000,
        "capital_currency": "CNY",
    }
    assert "确认" in payload["instruction"]


def test_propose_session_facts_rejects_negative_capital():
    tools, _ = _tools()
    with pytest.raises(ValueError):
        tools["propose_session_facts"].invoke({"available_capital": -1})


def test_propose_session_facts_rejects_bad_enum_and_pct():
    tools, _ = _tools()
    with pytest.raises(ValueError):
        tools["propose_session_facts"].invoke({"risk_tolerance": "wild"})
    with pytest.raises(ValueError):
        tools["propose_session_facts"].invoke({"max_single_position_pct": 150})


def test_propose_session_facts_requires_at_least_one_field():
    tools, _ = _tools()
    with pytest.raises(ValueError):
        tools["propose_session_facts"].invoke({})
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/advisor/test_profile_tools.py -q`
Expected: FAIL，`ModuleNotFoundError: tradingagents.advisor.profile_tools`。

- [ ] **Step 3: 实现工厂 + propose 工具**

创建 `tradingagents/advisor/profile_tools.py`：

```python
"""Session-profile tools: fact confirmation + enforced position sizing."""

from __future__ import annotations

import json
from collections.abc import Callable

from langchain_core.tools import BaseTool, tool

_RISK_VALUES = {"conservative", "balanced", "aggressive"}
_HORIZON_VALUES = {"short", "medium", "long"}
_CONFIRM_INSTRUCTION = (
    "已向用户弹出确认卡片，在用户确认前这些值未生效，不得据此计算。"
)


def create_profile_tools(*, load_profile: Callable[[], dict]) -> list[BaseTool]:
    """Build the profile tools. `load_profile` returns the confirmed profile dict."""

    @tool
    def propose_session_facts(
        available_capital: float | None = None,
        capital_currency: str | None = None,
        risk_tolerance: str | None = None,
        max_single_position_pct: float | None = None,
        horizon: str | None = None,
        constraints: str | None = None,
    ) -> str:
        """Propose key session facts for the user to confirm; does not take effect yet."""

        proposal: dict = {}
        if available_capital is not None:
            if available_capital < 0:
                raise ValueError("available_capital must be non-negative")
            proposal["available_capital"] = available_capital
        if capital_currency is not None:
            currency = capital_currency.strip()
            if not currency:
                raise ValueError("capital_currency must be nonblank")
            proposal["capital_currency"] = currency
        if risk_tolerance is not None:
            if risk_tolerance not in _RISK_VALUES:
                raise ValueError(f"risk_tolerance must be one of {_RISK_VALUES}")
            proposal["risk_tolerance"] = risk_tolerance
        if max_single_position_pct is not None:
            if not 0 < max_single_position_pct <= 100:
                raise ValueError("max_single_position_pct must be in (0, 100]")
            proposal["max_single_position_pct"] = max_single_position_pct
        if horizon is not None:
            if horizon not in _HORIZON_VALUES:
                raise ValueError(f"horizon must be one of {_HORIZON_VALUES}")
            proposal["horizon"] = horizon
        if constraints is not None:
            proposal["constraints"] = constraints

        if not proposal:
            raise ValueError("propose_session_facts requires at least one field")

        return json.dumps(
            {"proposal": proposal, "instruction": _CONFIRM_INSTRUCTION},
            ensure_ascii=False,
        )

    return [propose_session_facts]
```

> 注：本任务返回列表只含 `propose_session_facts`，Task 6 会把 `compute_position_sizing` 加进同一工厂的返回列表。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/advisor/test_profile_tools.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add tradingagents/advisor/profile_tools.py tests/advisor/test_profile_tools.py
git commit -m "feat(advisor): add propose_session_facts tool"
```

---

## Task 6: compute_position_sizing 工具

**Files:**
- Modify: `tradingagents/advisor/profile_tools.py`
- Test: `tests/advisor/test_profile_tools.py`

**Interfaces:**
- Produces（加入 `create_profile_tools` 返回列表）：
  - `compute_position_sizing(ticker: str, price: float, target_weight_pct: float | None = None, target_amount: float | None = None) -> str`
    - 从 `load_profile()` 读 `available_capital`、`capital_currency`、`max_single_position_pct`。
    - `available_capital` 为 None → 返回 `"NEED_CONFIRMATION: 缺少可用资金池，请先在参数面板确认"`。
    - `target_weight_pct` 与 `target_amount` 必须恰好提供一个，否则 `ValueError`。
    - `price` 必须 > 0，否则 `ValueError`。
    - 返回 JSON 字符串，含 `available_capital, capital_currency, target_weight_pct, amount, price, shares, max_single_position_pct, exceeds_max`。

- [ ] **Step 1: 写失败测试**

在 `tests/advisor/test_profile_tools.py` 末尾追加：

```python
def test_compute_position_sizing_needs_capital_when_unset():
    tools, _ = _tools(profile={})
    out = tools["compute_position_sizing"].invoke(
        {"ticker": "AAPL", "price": 200, "target_weight_pct": 10}
    )
    assert out.startswith("NEED_CONFIRMATION:")


def test_compute_position_sizing_by_weight():
    tools, _ = _tools(
        profile={"available_capital": 300000, "capital_currency": "CNY",
                 "max_single_position_pct": 25}
    )
    out = tools["compute_position_sizing"].invoke(
        {"ticker": "AAPL", "price": 200, "target_weight_pct": 10}
    )
    payload = json.loads(out)
    assert payload["amount"] == 30000
    assert payload["shares"] == 150
    assert payload["exceeds_max"] is False


def test_compute_position_sizing_flags_exceeding_max():
    tools, _ = _tools(
        profile={"available_capital": 300000, "max_single_position_pct": 25}
    )
    out = tools["compute_position_sizing"].invoke(
        {"ticker": "AAPL", "price": 100, "target_weight_pct": 40}
    )
    assert json.loads(out)["exceeds_max"] is True


def test_compute_position_sizing_by_amount_derives_weight():
    tools, _ = _tools(profile={"available_capital": 200000})
    out = tools["compute_position_sizing"].invoke(
        {"ticker": "AAPL", "price": 50, "target_amount": 50000}
    )
    payload = json.loads(out)
    assert payload["target_weight_pct"] == 25.0
    assert payload["shares"] == 1000


def test_compute_position_sizing_requires_exactly_one_target():
    tools, _ = _tools(profile={"available_capital": 200000})
    with pytest.raises(ValueError):
        tools["compute_position_sizing"].invoke({"ticker": "A", "price": 10})
    with pytest.raises(ValueError):
        tools["compute_position_sizing"].invoke(
            {"ticker": "A", "price": 10, "target_weight_pct": 5, "target_amount": 100}
        )


def test_compute_position_sizing_rejects_nonpositive_price():
    tools, _ = _tools(profile={"available_capital": 200000})
    with pytest.raises(ValueError):
        tools["compute_position_sizing"].invoke(
            {"ticker": "A", "price": 0, "target_weight_pct": 5}
        )
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/advisor/test_profile_tools.py -k compute -q`
Expected: FAIL，`KeyError: 'compute_position_sizing'`。

- [ ] **Step 3: 实现工具**

修改 `tradingagents/advisor/profile_tools.py`：在 `create_profile_tools` 内、`return` 语句**之前**，新增 `compute_position_sizing`，并把它加入返回列表。文件顶部加 `import math`。

新增的工具函数（放在 `propose_session_facts` 之后）：

```python
    @tool
    def compute_position_sizing(
        ticker: str,
        price: float,
        target_weight_pct: float | None = None,
        target_amount: float | None = None,
    ) -> str:
        """Compute position size from the confirmed available capital. Required for any sizing."""

        if (target_weight_pct is None) == (target_amount is None):
            raise ValueError(
                "provide exactly one of target_weight_pct or target_amount"
            )
        if price <= 0:
            raise ValueError("price must be positive")

        profile = load_profile() or {}
        available_capital = profile.get("available_capital")
        if available_capital is None:
            return "NEED_CONFIRMATION: 缺少可用资金池，请先在参数面板确认"

        currency = profile.get("capital_currency") or "CNY"
        max_pct = profile.get("max_single_position_pct")

        if target_weight_pct is not None:
            weight = float(target_weight_pct)
            amount = available_capital * weight / 100
        else:
            amount = float(target_amount)
            weight = amount / available_capital * 100 if available_capital else 0.0

        shares = math.floor(amount / price)
        exceeds_max = max_pct is not None and weight > max_pct + 1e-9

        return json.dumps(
            {
                "ticker": ticker,
                "available_capital": available_capital,
                "capital_currency": currency,
                "target_weight_pct": round(weight, 2),
                "amount": round(amount, 2),
                "price": price,
                "shares": shares,
                "max_single_position_pct": max_pct,
                "exceeds_max": exceeds_max,
            },
            ensure_ascii=False,
        )
```

并把返回行改为：

```python
    return [propose_session_facts, compute_position_sizing]
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/advisor/test_profile_tools.py -q`
Expected: PASS（全部用例）。

- [ ] **Step 5: 提交**

```bash
git add tradingagents/advisor/profile_tools.py tests/advisor/test_profile_tools.py
git commit -m "feat(advisor): add enforced compute_position_sizing tool"
```

---

## Task 7: prompt 注入档案段 + 行为准则

**Files:**
- Modify: `tradingagents/advisor/prompt.py`
- Test: `tests/advisor/test_prompt.py`

**Interfaces:**
- Produces: `build_system_prompt(report_context: str, holdings_ctx: str, profile_ctx: str = "") -> str`
  - 新增 `# 用户会话档案(已确认,强约束)` 段，内容为 `profile_ctx`（空则填占位说明）。
  - 新增 4 条行为准则关键词：`会话档案`、`重新推断`、`未设置`、`compute_position_sizing`、`NEED_CONFIRMATION`、`propose_session_facts`。
- Consumes: `profile_ctx` 由 Task 8 的 `chat.py::_profile_text` 提供。

- [ ] **Step 1: 写失败测试**

在 `tests/advisor/test_prompt.py` 末尾追加：

```python
def test_system_prompt_embeds_confirmed_profile():
    profile_ctx = "- 可用资金池: 300000 CNY\n- 风险偏好: 稳健"
    prompt = build_system_prompt("report", holdings_ctx="", profile_ctx=profile_ctx)
    assert "用户会话档案" in prompt
    assert "300000 CNY" in prompt
    assert "重新推断" in prompt


def test_system_prompt_enforces_sizing_and_confirmation_rules():
    prompt = build_system_prompt("report", holdings_ctx="")
    assert "compute_position_sizing" in prompt
    assert "NEED_CONFIRMATION" in prompt
    assert "propose_session_facts" in prompt
    assert "未设置" in prompt
```

并把现有 `test_system_prompt_embeds_report_and_holdings` 与
`test_system_prompt_handles_no_holdings`、
`test_system_prompt_defines_explicit_export_flow_and_success_rules` 保持不变（它们只传两个位置参数，`profile_ctx` 默认 `""` 仍兼容）。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/advisor/test_prompt.py -q`
Expected: FAIL（`用户会话档案`/`compute_position_sizing` 未出现）。

- [ ] **Step 3: 改模板与签名**

修改 `tradingagents/advisor/prompt.py`。

(a) 在 `_TEMPLATE` 的 `# 行为准则(强约束)` 列表里，于第 4 条"免责声明"之后追加：

```
5. 档案锚定:下方"用户会话档案"中的值是用户已确认的事实,必须直接使用,禁止重新推断或猜测;\
标注"未设置"的字段视为缺失。
6. 缺参数即问:当回答需要某会话档案字段(如计算仓位需可用资金池、判断集中度需单票最大仓位)\
而该字段未设置时,必须先反问用户补齐,不得使用默认值或猜测值计算。
7. 推断即复述:当你从对话中临时推断出一个尚未确认的关键事实时,必须先调用 propose_session_facts \
弹出确认卡片,在用户确认前不得据此给出操作建议。
8. 仓位计算:任何涉及配置金额、股数、仓位占比的计算,必须调用 compute_position_sizing 工具,\
禁止自行心算;当其返回以 NEED_CONFIRMATION: 开头时,按"缺参数即问"处理。
```

(b) 在 `# 分析报告上下文` 段**之前**新增一段：

```
# 用户会话档案(已确认,强约束)
{profile_context}
```

(c) 文件顶部新增占位常量，并改 `build_system_prompt`：

```python
_NO_PROFILE = "用户尚未确认任何会话参数。所有字段视为未设置。"


def build_system_prompt(
    report_context: str, holdings_ctx: str, profile_ctx: str = ""
) -> str:
    holdings = holdings_ctx.strip() if holdings_ctx and holdings_ctx.strip() else _NO_HOLDINGS
    profile = profile_ctx.strip() if profile_ctx and profile_ctx.strip() else _NO_PROFILE
    return _TEMPLATE.format(
        report_context=report_context,
        holdings_context=holdings,
        profile_context=profile,
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/advisor/test_prompt.py -q`
Expected: PASS（含原有用例）。

- [ ] **Step 5: 提交**

```bash
git add tradingagents/advisor/prompt.py tests/advisor/test_prompt.py
git commit -m "feat(advisor): inject confirmed profile and anchoring rules into prompt"
```

---

## Task 8: chat.py 装配（注入档案 + profile 工具）

**Files:**
- Modify: `api/routes/chat.py`
- Test: `tests/webui/test_routes_chat.py`

**Interfaces:**
- Consumes: `store.get_session_profile`（Task 2）、`build_system_prompt(.., profile_ctx)`（Task 7）、
  `create_profile_tools`（Task 5/6）。
- Produces: `_profile_text(profile: SessionProfile | None) -> str`（渲染中文档案段，未设置字段标"未设置"）。
  `stream_chat` 把 profile 注入 system prompt，并把 profile 工具装进 `tools`。

- [ ] **Step 1: 写失败测试**

在 `tests/webui/test_routes_chat.py` 末尾追加。该测试通过 fake chain 断言：(1) profile 工具已注册并可被调用；(2) 已确认的资金池注入了 system prompt。利用 fake LLM 第一轮请求调用 `compute_position_sizing`，第二轮产出文本：

```python
from langchain_core.messages import AIMessage


def test_stream_chat_registers_profile_tools_and_injects_profile(client):
    import api.main as main

    captured = {}

    class _RecordingChain:
        def __init__(self):
            self._round = 0

        def invoke(self, messages):
            # 记录注入的 system prompt（第一条消息由 prompt 模板渲染）
            self._round += 1
            if self._round == 1:
                captured["system"] = str(messages)
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "compute_position_sizing",
                        "args": {"ticker": "AAPL", "price": 200,
                                 "target_weight_pct": 10},
                        "id": "call1",
                    }],
                )
            return AIMessage(content="done")

    class _LLM:
        def bind_tools(self, tools):
            captured["tool_names"] = {t.name for t in tools}
            return _RecordingChain()

        def invoke(self, messages):
            return AIMessage(content="[]")

    main.app.state.chat_llm_factory = lambda: (_LLM(), _LLM())

    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    client.put(
        f"/api/chat/sessions/{sid}/profile",
        json={"available_capital": 300000, "capital_currency": "CNY"},
    )
    with client.stream(
        "POST", f"/api/chat/sessions/{sid}/stream", json={"message": "AAPL 配 10%"}
    ) as resp:
        body = "".join(resp.iter_text())

    assert "compute_position_sizing" in captured["tool_names"]
    assert "propose_session_facts" in captured["tool_names"]
    assert "300000" in captured["system"]
    assert "done" in body
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_chat.py -k profile_tools -q`
Expected: FAIL（profile 工具未注册 / 资金池未注入）。

- [ ] **Step 3: import 与渲染助手**

修改 `api/routes/chat.py`：

(a) 顶部 import 增加：

```python
from tradingagents.advisor.profile_tools import create_profile_tools
```

(b) 在 `_holdings_text` 函数之后新增渲染助手：

```python
_RISK_LABELS = {"conservative": "保守", "balanced": "稳健", "aggressive": "激进"}
_HORIZON_LABELS = {"short": "短期", "medium": "中期", "long": "长期"}


def _profile_text(profile: SessionProfile | None) -> str:
    p = profile or SessionProfile()
    capital = (
        f"{p.available_capital:g} {p.capital_currency}"
        if p.available_capital is not None
        else "未设置"
    )
    risk = _RISK_LABELS.get(p.risk_tolerance, "未设置")
    max_pos = (
        f"{p.max_single_position_pct:g}%"
        if p.max_single_position_pct is not None
        else "未设置"
    )
    horizon = _HORIZON_LABELS.get(p.horizon, "未设置")
    constraints = p.constraints.strip() if p.constraints and p.constraints.strip() else "未设置"
    return (
        f"- 可用资金池: {capital}\n"
        f"- 风险偏好: {risk}\n"
        f"- 单票最大仓位: {max_pos}\n"
        f"- 投资期限: {horizon}\n"
        f"- 偏好/禁投: {constraints}"
    )
```

- [ ] **Step 4: 注入 prompt + 装配工具**

在 `stream_chat` 内修改：

(a) 在构造 `system_prompt` 处加入 profile：

```python
    holdings, _ = store.get_portfolio(session_id)
    holdings_ctx = _holdings_text(holdings)
    profile_ctx = _profile_text(store.get_session_profile(session_id))
    system_prompt = build_system_prompt(report_ctx, holdings_ctx, profile_ctx)
```

(b) 在 `export_tools = create_export_tools(...)` 之后、`tools = [...]` 处加入 profile 工具：

```python
    def load_profile() -> dict:
        current = store.get_session_profile(session_id)
        return current.model_dump() if current else {}

    profile_tools = create_profile_tools(load_profile=load_profile)
    tools = [*ADVISOR_TOOLS, *profile_tools, *export_tools]
```

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_chat.py -q`
Expected: PASS（新用例 + 原有 chat 路由用例）。

- [ ] **Step 6: 跑后端全量 + lint**

Run: `.venv/bin/python -m pytest -m "not integration" -q && ruff check .`
Expected: 全绿。

- [ ] **Step 7: 提交**

```bash
git add api/routes/chat.py tests/webui/test_routes_chat.py
git commit -m "feat(chat): inject session profile and wire profile tools"
```

---

## Task 9: 前端类型与 API 客户端

**Files:**
- Modify: `webui/lib/types.ts`、`webui/lib/api.ts`

**Interfaces:**
- Produces:
  - `SessionProfile` TS 接口（与后端字段一致）。
  - `getSessionProfile(id: string): Promise<SessionProfile>`
  - `saveSessionProfile(id: string, profile: SessionProfile): Promise<SessionProfile>`

- [ ] **Step 1: 读 Next.js 16 文档**

阅读 `webui/node_modules/next/dist/docs/` 中与 client component / fetch 相关的说明，确认无破坏性差异影响普通 `fetch` 调用。

- [ ] **Step 2: 加类型**

在 `webui/lib/types.ts` 末尾追加：

```typescript
export type RiskTolerance = "conservative" | "balanced" | "aggressive";
export type InvestmentHorizon = "short" | "medium" | "long";

export interface SessionProfile {
  available_capital: number | null;
  capital_currency: string;
  risk_tolerance: RiskTolerance | null;
  max_single_position_pct: number | null;
  horizon: InvestmentHorizon | null;
  constraints: string | null;
  confirmed_at: string | null;
}
```

- [ ] **Step 3: 加 API 客户端**

在 `webui/lib/api.ts`：顶部 import 增加 `SessionProfile`：

```typescript
import type {
  AnalysisRequest,
  ChatMessageT,
  ChatSessionT,
  ConfigOptions,
  HistorySummary,
  PortfolioHolding,
  RunResult,
  RunStatusDetail,
  SessionProfile,
} from "./types";
```

文件末尾（`chatStreamUrl` 之后）追加：

```typescript
export async function getSessionProfile(id: string): Promise<SessionProfile> {
  const r = await fetch(`${BASE}/api/chat/sessions/${id}/profile`);
  if (!r.ok) throw new Error("无法加载会话参数");
  return r.json();
}

export async function saveSessionProfile(
  id: string,
  profile: SessionProfile,
): Promise<SessionProfile> {
  const r = await fetch(`${BASE}/api/chat/sessions/${id}/profile`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
  });
  if (!r.ok) throw new Error("无法保存会话参数");
  return r.json();
}
```

- [ ] **Step 4: 类型检查**

Run: `cd webui && npx tsc --noEmit`
Expected: 无新增类型错误。

- [ ] **Step 5: 提交**

```bash
git add webui/lib/types.ts webui/lib/api.ts
git commit -m "feat(webui): add SessionProfile type and API client"
```

---

## Task 10: chat-profile.ts 解析助手 + 测试

**Files:**
- Create: `webui/lib/chat-profile.ts`、`webui/lib/chat-profile.test.ts`
- Modify: `webui/lib/chat-export.ts`（把 `propose_session_facts` 归为内部工具，不显示为数据来源）

**Interfaces:**
- Produces:
  - `sessionFactsProposal(message: ChatMessageT): Partial<SessionProfile> | null`
    —— 读取 `propose_session_facts` tool_call 的 `args.proposal`（兼容直接 args 形式），无则返回 `null`。

- [ ] **Step 1: 写失败测试**

创建 `webui/lib/chat-profile.test.ts`：

```typescript
import assert from "node:assert/strict";
import test from "node:test";

import { sessionFactsProposal } from "./chat-profile.ts";
import type { ChatMessageT } from "./types.ts";

function message(toolCalls: Record<string, unknown>[]): ChatMessageT {
  return {
    message_id: "m1",
    session_id: "s1",
    role: "assistant",
    content: "",
    tool_calls: toolCalls,
    created_at: "2026-06-22T00:00:00Z",
  };
}

test("sessionFactsProposal reads proposal from propose_session_facts call", () => {
  const result = sessionFactsProposal(
    message([
      {
        tool: "propose_session_facts",
        args: { available_capital: 300000, capital_currency: "CNY" },
      },
    ]),
  );
  assert.deepEqual(result, { available_capital: 300000, capital_currency: "CNY" });
});

test("sessionFactsProposal returns null without the tool", () => {
  assert.equal(sessionFactsProposal(message([{ tool: "get_stock_data" }])), null);
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd webui && node --no-warnings --test --experimental-strip-types lib/chat-profile.test.ts`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现解析助手**

创建 `webui/lib/chat-profile.ts`：

```typescript
import type { ChatMessageT, SessionProfile } from "@/lib/types";

const PROFILE_FIELDS: (keyof SessionProfile)[] = [
  "available_capital",
  "capital_currency",
  "risk_tolerance",
  "max_single_position_pct",
  "horizon",
  "constraints",
];

export function sessionFactsProposal(
  message: ChatMessageT,
): Partial<SessionProfile> | null {
  const call = message.tool_calls.find(
    (item) => item.tool === "propose_session_facts",
  );
  const args = call?.args;
  if (!args || typeof args !== "object") return null;
  // 后端工具返回 {proposal: {...}}; LangChain 记录的是入参本身，故二者都兼容
  const source = ((args as { proposal?: unknown }).proposal ?? args) as Record<
    string,
    unknown
  >;
  const proposal: Partial<SessionProfile> = {};
  for (const field of PROFILE_FIELDS) {
    if (source[field] !== undefined && source[field] !== null) {
      // @ts-expect-error narrow per-field assignment from untrusted payload
      proposal[field] = source[field];
    }
  }
  return Object.keys(proposal).length > 0 ? proposal : null;
}
```

- [ ] **Step 4: 内部工具集合排除 propose_session_facts**

修改 `webui/lib/chat-export.ts` 的 `INTERNAL_EXPORT_TOOLS`，加入新工具名：

```typescript
const INTERNAL_EXPORT_TOOLS = new Set([
  "request_export_scope",
  "export_chat_report",
  "propose_session_facts",
]);
```

- [ ] **Step 5: 运行确认通过**

Run: `cd webui && npm test`
Expected: PASS（含原有 chat-export 测试）。

- [ ] **Step 6: 提交**

```bash
git add webui/lib/chat-profile.ts webui/lib/chat-profile.test.ts webui/lib/chat-export.ts
git commit -m "feat(webui): parse session-fact proposals from tool calls"
```

---

## Task 11: ProfilePanel 面板 + 页面装配

**Files:**
- Create: `webui/components/chat/ProfilePanel.tsx`
- Modify: `webui/app/chat/page.tsx`

**Interfaces:**
- Consumes: `SessionProfile`（Task 9）、`getSessionProfile`/`saveSessionProfile`（Task 9）。
- Produces: `<ProfilePanel value={profile} onChange={(p) => ...} disabled={...} />`
  - `value: SessionProfile`、`onChange: (next: SessionProfile) => void`、`disabled?: boolean`。

- [ ] **Step 1: 读 Next.js 16 文档**

阅读 `webui/node_modules/next/dist/docs/` 中关于 client component 表单/受控输入的说明，确认无破坏性差异。

- [ ] **Step 2: 实现 ProfilePanel**

创建 `webui/components/chat/ProfilePanel.tsx`（受控表单，"保存"触发 `onChange`）：

```tsx
"use client";

import { useEffect, useState } from "react";
import type {
  InvestmentHorizon,
  RiskTolerance,
  SessionProfile,
} from "@/lib/types";

const RISK_OPTIONS: { value: RiskTolerance; label: string }[] = [
  { value: "conservative", label: "保守" },
  { value: "balanced", label: "稳健" },
  { value: "aggressive", label: "激进" },
];
const HORIZON_OPTIONS: { value: InvestmentHorizon; label: string }[] = [
  { value: "short", label: "短期" },
  { value: "medium", label: "中期" },
  { value: "long", label: "长期" },
];

export function ProfilePanel({
  value,
  onChange,
  disabled = false,
}: {
  value: SessionProfile;
  onChange: (next: SessionProfile) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState<SessionProfile>(value);
  useEffect(() => setDraft(value), [value]);

  const num = (raw: string): number | null => {
    const n = Number(raw);
    return raw.trim() === "" || Number.isNaN(n) ? null : n;
  };

  return (
    <div className="space-y-2 text-sm">
      <label className="block">
        <span className="text-xs text-muted-foreground">可用资金池</span>
        <div className="mt-1 flex gap-2">
          <input
            type="number"
            className="glass-control min-w-0 flex-1 rounded-md px-2 py-1.5 outline-none focus:border-primary"
            value={draft.available_capital ?? ""}
            onChange={(e) =>
              setDraft({ ...draft, available_capital: num(e.target.value) })
            }
            disabled={disabled}
            aria-label="可用资金池"
          />
          <input
            type="text"
            className="glass-control w-20 rounded-md px-2 py-1.5 outline-none focus:border-primary"
            value={draft.capital_currency}
            onChange={(e) =>
              setDraft({ ...draft, capital_currency: e.target.value })
            }
            disabled={disabled}
            aria-label="币种"
          />
        </div>
      </label>

      <label className="block">
        <span className="text-xs text-muted-foreground">风险偏好</span>
        <select
          className="glass-control mt-1 w-full rounded-md px-2 py-1.5 outline-none focus:border-primary"
          value={draft.risk_tolerance ?? ""}
          onChange={(e) =>
            setDraft({
              ...draft,
              risk_tolerance: (e.target.value || null) as RiskTolerance | null,
            })
          }
          disabled={disabled}
          aria-label="风险偏好"
        >
          <option value="">未设置</option>
          {RISK_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      <label className="block">
        <span className="text-xs text-muted-foreground">单票最大仓位 (%)</span>
        <input
          type="number"
          className="glass-control mt-1 w-full rounded-md px-2 py-1.5 outline-none focus:border-primary"
          value={draft.max_single_position_pct ?? ""}
          onChange={(e) =>
            setDraft({ ...draft, max_single_position_pct: num(e.target.value) })
          }
          disabled={disabled}
          aria-label="单票最大仓位"
        />
      </label>

      <label className="block">
        <span className="text-xs text-muted-foreground">投资期限</span>
        <select
          className="glass-control mt-1 w-full rounded-md px-2 py-1.5 outline-none focus:border-primary"
          value={draft.horizon ?? ""}
          onChange={(e) =>
            setDraft({
              ...draft,
              horizon: (e.target.value || null) as InvestmentHorizon | null,
            })
          }
          disabled={disabled}
          aria-label="投资期限"
        >
          <option value="">未设置</option>
          {HORIZON_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      <label className="block">
        <span className="text-xs text-muted-foreground">偏好 / 禁投</span>
        <textarea
          className="glass-control mt-1 w-full rounded-md px-2 py-1.5 outline-none focus:border-primary"
          rows={2}
          value={draft.constraints ?? ""}
          onChange={(e) =>
            setDraft({ ...draft, constraints: e.target.value || null })
          }
          disabled={disabled}
          aria-label="偏好或禁投约束"
        />
      </label>

      <button
        type="button"
        onClick={() => onChange(draft)}
        disabled={disabled}
        className="glass-control w-full rounded-md px-3 py-1.5 text-sm transition-colors hover:border-primary/60 hover:text-primary disabled:cursor-not-allowed disabled:opacity-45"
      >
        保存参数
      </button>
    </div>
  );
}
```

- [ ] **Step 3: 页面装配 — state 与加载**

修改 `webui/app/chat/page.tsx`：

(a) import 增加：

```tsx
import { ProfilePanel } from "@/components/chat/ProfilePanel";
import { getSessionProfile, saveSessionProfile } from "@/lib/api";
import type { SessionProfile } from "@/lib/types";
```

（把 `getSessionProfile, saveSessionProfile` 合并进现有 `@/lib/api` 的 import，把 `SessionProfile` 合并进现有 `@/lib/types` 的 import。）

(b) 新增空档案常量与 state（放在组件函数体内、`holdings` state 附近）：

```tsx
  const emptyProfile: SessionProfile = {
    available_capital: null,
    capital_currency: "CNY",
    risk_tolerance: null,
    max_single_position_pct: null,
    horizon: null,
    constraints: null,
    confirmed_at: null,
  };
  const [profile, setProfile] = useState<SessionProfile>(emptyProfile);
```

(c) 在 `openSession` 内、加载 portfolio 之后追加加载 profile：

```tsx
    const loadedProfile = await getSessionProfile(data.session.session_id).catch(
      () => emptyProfile,
    );
    setProfile(loadedProfile);
```

(d) 新增持久化函数（放在 `persistHoldings` 附近）：

```tsx
  const persistProfile = async (next: SessionProfile) => {
    setProfile(next);
    if (sessionId) {
      const saved = await saveSessionProfile(sessionId, next).catch(() => null);
      if (saved) setProfile(saved);
    }
  };
```

- [ ] **Step 4: 页面装配 — 渲染面板**

在 `webui/app/chat/page.tsx` 右侧 `<aside>` 内，`RunPicker` 容器之后、持仓容器之前，插入面板块：

```tsx
          <div className="glass-readable shrink-0 rounded-lg px-3 py-3">
            <div className="mb-2 font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
              会话参数
            </div>
            <ProfilePanel
              value={profile}
              onChange={(next) => void persistProfile(next)}
              disabled={streaming || !sessionId}
            />
          </div>
```

- [ ] **Step 5: 类型检查 + 构建**

Run: `cd webui && npx tsc --noEmit && npm run lint`
Expected: 无错误。

- [ ] **Step 6: 提交**

```bash
git add webui/components/chat/ProfilePanel.tsx webui/app/chat/page.tsx
git commit -m "feat(webui): add session profile panel"
```

---

## Task 12: 确认卡片渲染与确认回调

**Files:**
- Create: `webui/components/chat/ProfileProposalCard.tsx`
- Modify: `webui/components/chat/ChatMessage.tsx`、`webui/app/chat/page.tsx`

**Interfaces:**
- Consumes: `sessionFactsProposal`（Task 10）、`persistProfile`（Task 11）、`SessionProfile`（Task 9）。
- Produces:
  - `<ProfileProposalCard proposal={...} disabled={...} onConfirm={(merged) => ...} onDismiss={() => ...} />`
  - `ChatMessage` 新增可选 prop：`profile: SessionProfile`、`profileActionsEnabled?: boolean`、
    `onConfirmFacts?: (merged: SessionProfile) => void`、`onDismissFacts?: () => void`。

- [ ] **Step 1: 读 Next.js 16 文档**

确认 client component 内嵌套表单/按钮无破坏性差异（同 Task 11 已读，可跳过重复阅读）。

- [ ] **Step 2: 实现 ProfileProposalCard**

创建 `webui/components/chat/ProfileProposalCard.tsx`（预填可改字段，"确认填入 / 忽略"）：

```tsx
"use client";

import { useState } from "react";
import type { SessionProfile } from "@/lib/types";

const FIELD_LABELS: Record<string, string> = {
  available_capital: "可用资金池",
  capital_currency: "币种",
  risk_tolerance: "风险偏好",
  max_single_position_pct: "单票最大仓位(%)",
  horizon: "投资期限",
  constraints: "偏好/禁投",
};

export function ProfileProposalCard({
  proposal,
  current,
  disabled = false,
  onConfirm,
  onDismiss,
}: {
  proposal: Partial<SessionProfile>;
  current: SessionProfile;
  disabled?: boolean;
  onConfirm: (merged: SessionProfile) => void;
  onDismiss: () => void;
}) {
  const [draft, setDraft] = useState<Partial<SessionProfile>>(proposal);
  const entries = Object.keys(proposal) as (keyof SessionProfile)[];

  return (
    <div className="mt-3 rounded-md border border-primary/30 bg-primary/5 p-3" aria-label="会话参数确认卡片">
      <div className="mb-2 text-xs text-muted-foreground">
        请确认以下参数将写入会话档案：
      </div>
      <div className="space-y-1.5">
        {entries.map((field) => (
          <label key={field} className="flex items-center gap-2 text-sm">
            <span className="w-28 shrink-0 text-xs text-muted-foreground">
              {FIELD_LABELS[field] ?? field}
            </span>
            <input
              type="text"
              className="glass-control min-w-0 flex-1 rounded-md px-2 py-1 outline-none focus:border-primary"
              value={String(draft[field] ?? "")}
              onChange={(e) =>
                setDraft({ ...draft, [field]: e.target.value })
              }
              disabled={disabled}
              aria-label={FIELD_LABELS[field] ?? String(field)}
            />
          </label>
        ))}
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={() => onConfirm({ ...current, ...coerce(draft) })}
          className="glass-control rounded-md px-2.5 py-1.5 text-xs transition-colors hover:border-primary/60 hover:text-primary disabled:cursor-not-allowed disabled:opacity-45"
        >
          确认填入
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={onDismiss}
          className="glass-control rounded-md px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:border-destructive/50 hover:text-destructive disabled:cursor-not-allowed disabled:opacity-45"
        >
          忽略
        </button>
      </div>
    </div>
  );
}

function coerce(draft: Partial<SessionProfile>): Partial<SessionProfile> {
  const out: Partial<SessionProfile> = { ...draft };
  for (const key of ["available_capital", "max_single_position_pct"] as const) {
    if (out[key] !== undefined) {
      const n = Number(out[key]);
      out[key] = Number.isNaN(n) ? null : n;
    }
  }
  return out;
}
```

- [ ] **Step 3: ChatMessage 渲染卡片**

修改 `webui/components/chat/ChatMessage.tsx`：

(a) import 增加：

```tsx
import { sessionFactsProposal } from "@/lib/chat-profile";
import { ProfileProposalCard } from "@/components/chat/ProfileProposalCard";
import type { ChatMessageT, SessionProfile } from "@/lib/types";
```

（与现有 `ChatMessageT` 的 import 合并。）

(b) 扩展组件 props 签名：

```tsx
export function ChatMessage({
  message,
  choicesEnabled = false,
  onChoice,
  profile,
  profileActionsEnabled = false,
  onConfirmFacts,
  onDismissFacts,
}: {
  message: ChatMessageT;
  choicesEnabled?: boolean;
  onChoice?: (choice: string) => void;
  profile?: SessionProfile;
  profileActionsEnabled?: boolean;
  onConfirmFacts?: (merged: SessionProfile) => void;
  onDismissFacts?: () => void;
}) {
```

(c) 在函数体内计算提议：

```tsx
  const proposal = sessionFactsProposal(message);
```

(d) 在 `dataSources` 渲染块之前插入卡片渲染（仅 assistant 消息、有提议、且传入了 profile 时）：

```tsx
        {proposal && profile && (
          <ProfileProposalCard
            proposal={proposal}
            current={profile}
            disabled={!profileActionsEnabled}
            onConfirm={(merged) => onConfirmFacts?.(merged)}
            onDismiss={() => onDismissFacts?.()}
          />
        )}
```

- [ ] **Step 4: page.tsx 装配确认回调**

修改 `webui/app/chat/page.tsx`：

(a) 新增"已忽略提议"集合 state（放在其他 state 附近）：

```tsx
  const [dismissedProposals, setDismissedProposals] = useState<Set<string>>(new Set());
```

(b) 新增确认处理（放在 `persistProfile` 之后）。确认后写库并补发一条消息，让 LLM 据更新后的档案继续：

```tsx
  const confirmFacts = async (messageId: string, merged: SessionProfile) => {
    await persistProfile(merged);
    setDismissedProposals((ids) => new Set(ids).add(messageId));
    void sendMessage("我已确认会话参数面板，请据此继续。");
  };

  const dismissFacts = (messageId: string) => {
    setDismissedProposals((ids) => new Set(ids).add(messageId));
  };
```

(c) 在消息列表渲染处给 `ChatMessage` 传入新 props：

```tsx
              <ChatMessage
                key={message.message_id}
                message={message}
                choicesEnabled={
                  message.message_id === activeChoiceMessageId && !streaming
                }
                onChoice={(choice) => void sendMessage(choice)}
                profile={profile}
                profileActionsEnabled={
                  !streaming && !dismissedProposals.has(message.message_id)
                }
                onConfirmFacts={(merged) => void confirmFacts(message.message_id, merged)}
                onDismissFacts={() => dismissFacts(message.message_id)}
              />
```

- [ ] **Step 5: 类型检查 + lint**

Run: `cd webui && npx tsc --noEmit && npm run lint && npm test`
Expected: 无错误，前端测试通过。

- [ ] **Step 6: 提交**

```bash
git add webui/components/chat/ProfileProposalCard.tsx webui/components/chat/ChatMessage.tsx webui/app/chat/page.tsx
git commit -m "feat(webui): render session-fact confirmation card"
```

---

## Task 13: CHANGELOG 与收尾

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 更新 CHANGELOG**

在 `CHANGELOG.md` 的 `[Unreleased]` 段 `### Added` 下追加（无该子标题则新建）：

```markdown
### Added
- Chat 会话档案 Harness：新增可用资金池/风险偏好/单票上限/投资期限等会话参数面板，
  确认后稳定注入每轮推理；新增 `propose_session_facts`（对话抽取→确认卡片）与
  `compute_position_sizing`（强制使用已确认资金池、缺失则返回 `NEED_CONFIRMATION` 反问）工具。
```

- [ ] **Step 2: 全量验证**

Run: `.venv/bin/python -m pytest -m "not integration" -q && ruff check . && cd webui && npx tsc --noEmit && npm test && npm run lint`
Expected: 全绿。

- [ ] **Step 3: 提交**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): record chat session profile harness"
```

---

## Self-Review 检查记录

- **Spec 覆盖**：数据模型(T1/T2)、prompt 注入(T7)、propose 工具(T5)、compute 工具(T6)、
  NEED_CONFIRMATION 哨兵(T4)、路由(T3)、chat 装配(T8)、面板(T11)、确认卡片(T10/T12)、
  错误处理（GET 返回默认档案 T3、工具非法值抛错经 engine 兜底、前端解析失败返回 null T10）、
  测试（store/工具/prompt/路由/前端解析）均有对应任务。
- **类型一致**：`build_system_prompt(report, holdings_ctx, profile_ctx="")`、
  `create_profile_tools(load_profile=...)`、`compute_position_sizing(ticker, price, target_weight_pct, target_amount)`、
  `sessionFactsProposal(message)`、`SessionProfile` 字段在前后端任务中保持一致。
- **无占位符**：所有步骤含真实代码与可运行命令。
