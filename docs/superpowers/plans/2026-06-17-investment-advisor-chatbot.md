# 投资操作顾问 Chatbot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 TradingAgents WebUI 中新增一个投资操作顾问对话机器人,基于已完成的分析报告 + 实时数据工具 + 上传截图提取的持仓,给出有研究依据的具体操作建议。

**Architecture:** 独立的 `tradingagents/advisor/` 模块封装对话引擎(手写 `prompt | llm.bind_tools(tools)` 工具循环 + 视觉持仓提取 + 报告上下文组装),`api/routes/chat.py` 用现有 `queue.Queue → asyncio.to_thread → EventSourceResponse` 模式做 SSE 流式;3 张新 SQLite 表持久化会话/消息/持仓;Next.js `/chat` 新页面复用现有 base-nova 组件与 EventSource。

**Tech Stack:** Python 3.10+, FastAPI, sse-starlette, LangChain (`bind_tools` + 多模态 HumanMessage), SQLite, Next.js 16 App Router, Tailwind 4 / `@base-ui/react`, pytest (`-m unit`)。

参考 spec: `docs/superpowers/specs/2026-06-17-investment-advisor-chatbot-design.md`

---

## File Structure

| 文件 | 职责 |
|---|---|
| `api/schemas.py` (修改) | 追加 `PortfolioHolding` / `ChatRequest` / `ChatSessionCreate` / `ChatMessage` / `ChatSession` / `PortfolioExtractResponse` + `ChatRole` Literal |
| `api/store.py` (修改) | `_SCHEMA` 追加 3 表 + 会话/消息/持仓 CRUD 方法 |
| `tradingagents/advisor/__init__.py` (新建) | 模块导出 |
| `tradingagents/advisor/tools.py` (新建) | 收集 dataflows `@tool` 列表 + `NO_DATA_` 前缀判定 |
| `tradingagents/advisor/prompt.py` (新建) | 系统提示词(角色/引用规则/持仓感知/免责/诚实约束) |
| `tradingagents/advisor/context.py` (新建) | 从 `result_json` 组装 7 报告字段为上下文文本 |
| `tradingagents/advisor/vision.py` (新建) | 截图 base64 → 多模态 HumanMessage → 结构化持仓提取 + 解析 |
| `tradingagents/advisor/engine.py` (新建) | 工具调用循环,产出 SSE 事件 dict 序列 |
| `api/routes/chat.py` (新建) | 会话 CRUD + 持仓提取/覆盖 + 流式对话端点 |
| `api/main.py` (修改) | 注册 chat router + `chat_llm_factory` 注入点 + state 字段 |
| `webui/lib/types.ts` (修改) | chat 相关 TS 类型 |
| `webui/lib/api.ts` (修改) | chat API 调用 |
| `webui/lib/sse.ts` (修改) | chat token 流订阅 |
| `webui/app/chat/page.tsx` (新建) | 对话页面 |
| `webui/components/chat/*.tsx` (新建) | ChatMessage / PortfolioUpload / HoldingsTable / RunPicker |

测试文件:`tests/webui/test_chat_store.py`, `tests/webui/test_chat_schemas.py`, `tests/advisor/test_tools.py`, `tests/advisor/test_context.py`, `tests/advisor/test_vision.py`, `tests/advisor/test_engine.py`, `tests/webui/test_routes_chat.py`。

---

## Task 1: Chat Pydantic schemas

**Files:**
- Modify: `api/schemas.py`
- Test: `tests/webui/test_chat_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/webui/test_chat_schemas.py
import pytest
from pydantic import ValidationError

from api.schemas import (
    ChatMessage,
    ChatRequest,
    ChatSession,
    ChatSessionCreate,
    PortfolioExtractResponse,
    PortfolioHolding,
)


def test_portfolio_holding_only_ticker_required():
    h = PortfolioHolding(ticker="AAPL")
    assert h.ticker == "AAPL"
    assert h.shares is None
    assert h.action is None


def test_portfolio_holding_action_literal_rejects_bad_value():
    with pytest.raises(ValidationError):
        PortfolioHolding(ticker="AAPL", action="hodl")


def test_chat_message_role_literal():
    m = ChatMessage(
        message_id="m1",
        session_id="s1",
        role="assistant",
        content="hello",
        created_at="2026-06-17T00:00:00+00:00",
    )
    assert m.role == "assistant"
    assert m.tool_calls == []


def test_chat_session_create_run_id_optional():
    assert ChatSessionCreate().run_id is None
    assert ChatSessionCreate(run_id="r1").run_id == "r1"


def test_portfolio_extract_response_defaults():
    r = PortfolioExtractResponse(source="vision")
    assert r.holdings == []
    assert r.source == "vision"


def test_chat_request_message_required():
    with pytest.raises(ValidationError):
        ChatRequest()
    assert ChatRequest(message="hi").message == "hi"


def test_chat_session_shape():
    s = ChatSession(
        session_id="s1",
        run_id=None,
        title="AAPL chat",
        created_at="2026-06-17T00:00:00+00:00",
        updated_at="2026-06-17T00:00:00+00:00",
    )
    assert s.session_id == "s1"
    assert s.run_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/webui/test_chat_schemas.py -v`
Expected: FAIL with `ImportError: cannot import name 'PortfolioHolding'`

- [ ] **Step 3: Append models to `api/schemas.py`**

Add after the existing `ConfigOptions` class (file currently ends at line 62). Reuse existing `Literal`, `BaseModel`, `Field` imports already at top of file:

```python
ChatRole = Literal["user", "assistant"]
PortfolioSource = Literal["vision", "manual"]


class PortfolioHolding(BaseModel):
    ticker: str
    name: str | None = None
    shares: float | None = None
    avg_cost: float | None = None
    market_value: float | None = None
    weight: float | None = None
    action: Literal["buy", "sell"] | None = None
    trade_date: str | None = None


class ChatRequest(BaseModel):
    message: str


class ChatSessionCreate(BaseModel):
    run_id: str | None = None


class ChatMessage(BaseModel):
    message_id: str
    session_id: str
    role: ChatRole
    content: str
    tool_calls: list[dict] = Field(default_factory=list)
    created_at: str


class ChatSession(BaseModel):
    session_id: str
    run_id: str | None
    title: str | None
    created_at: str
    updated_at: str


class PortfolioExtractResponse(BaseModel):
    holdings: list[PortfolioHolding] = Field(default_factory=list)
    source: PortfolioSource
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/webui/test_chat_schemas.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add api/schemas.py tests/webui/test_chat_schemas.py
git commit -m "feat(advisor): add chat pydantic schemas"
```

---

## Task 2: SQLite store — chat tables and CRUD

**Files:**
- Modify: `api/store.py`
- Test: `tests/webui/test_chat_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/webui/test_chat_store.py
from api.schemas import PortfolioHolding
from api.store import Store


def test_create_and_get_chat_session(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id="r1", title="AAPL")
    s = store.get_chat_session("s1")
    assert s.session_id == "s1"
    assert s.run_id == "r1"
    assert s.title == "AAPL"


def test_list_chat_sessions_newest_first(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title="one")
    store.create_chat_session("s2", run_id=None, title="two")
    ids = [s.session_id for s in store.list_chat_sessions()]
    assert ids[0] == "s2"


def test_insert_and_list_chat_messages(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title=None)
    store.insert_chat_message("m1", "s1", "user", "hi", tool_calls=[])
    store.insert_chat_message(
        "m2", "s1", "assistant", "hello", tool_calls=[{"tool": "get_stock_data"}]
    )
    msgs = store.list_chat_messages("s1")
    assert [m.message_id for m in msgs] == ["m1", "m2"]
    assert msgs[1].tool_calls == [{"tool": "get_stock_data"}]


def test_save_and_get_portfolio_overwrites(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title=None)
    store.save_portfolio(
        "s1", [PortfolioHolding(ticker="AAPL", shares=10)], source="vision"
    )
    store.save_portfolio(
        "s1", [PortfolioHolding(ticker="MSFT", shares=5)], source="manual"
    )
    holdings, source = store.get_portfolio("s1")
    assert source == "manual"
    assert [h.ticker for h in holdings] == ["MSFT"]


def test_get_portfolio_missing_returns_empty(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title=None)
    holdings, source = store.get_portfolio("s1")
    assert holdings == []
    assert source is None


def test_delete_chat_session_cascades_messages(tmp_path):
    store = Store(tmp_path / "t.db")
    store.create_chat_session("s1", run_id=None, title=None)
    store.insert_chat_message("m1", "s1", "user", "hi", tool_calls=[])
    store.delete_chat_session("s1")
    assert store.get_chat_session("s1") is None
    assert store.list_chat_messages("s1") == []


def test_chat_tables_coexist_with_existing_db(tmp_path):
    # An existing analysis_runs DB must still work after schema extension.
    store = Store(tmp_path / "t.db")
    store.insert_run("r1", "NVDA", "2024-05-10", "stock", {})
    assert store.get_run("r1").status == "running"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/webui/test_chat_store.py -v`
Expected: FAIL with `AttributeError: 'Store' object has no attribute 'create_chat_session'`

- [ ] **Step 3a: Extend `_SCHEMA` in `api/store.py`**

Replace the `_SCHEMA` string (lines 12-25) so it keeps `analysis_runs` and appends the three chat tables:

```python
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

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id    TEXT PRIMARY KEY,
    run_id        TEXT,
    title         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id      TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    tool_calls_json TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_portfolios (
    session_id    TEXT PRIMARY KEY,
    holdings_json TEXT NOT NULL,
    source        TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
"""
```

- [ ] **Step 3b: Add the import and CRUD methods**

At the top of `api/store.py`, extend the existing schema import (line 10) to also import the chat models:

```python
from api.schemas import ChatMessage, ChatSession, HistorySummary, PortfolioHolding, RunResult
```

Add these methods to the `Store` class (after `has_running_run`, the current last method at line 172):

```python
    # ---- chat sessions ----

    def create_chat_session(
        self, session_id: str, run_id: str | None, title: str | None
    ) -> None:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_sessions "
                "(session_id, run_id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, run_id, title, now, now),
            )

    def get_chat_session(self, session_id: str) -> ChatSession | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return ChatSession(
            session_id=row["session_id"],
            run_id=row["run_id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_chat_sessions(self) -> list[ChatSession]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_sessions ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()
        return [
            ChatSession(
                session_id=r["session_id"],
                run_id=r["run_id"],
                title=r["title"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def delete_chat_session(self, session_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM chat_portfolios WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM chat_sessions WHERE session_id=?", (session_id,))

    def _touch_session(self, conn: sqlite3.Connection, session_id: str) -> None:
        conn.execute(
            "UPDATE chat_sessions SET updated_at=? WHERE session_id=?",
            (_now(), session_id),
        )

    # ---- chat messages ----

    def insert_chat_message(
        self,
        message_id: str,
        session_id: str,
        role: str,
        content: str,
        tool_calls: list[dict],
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_messages "
                "(message_id, session_id, role, content, tool_calls_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (message_id, session_id, role, content, _dumps(tool_calls), _now()),
            )
            self._touch_session(conn, session_id)

    def list_chat_messages(self, session_id: str) -> list[ChatMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id=? "
                "ORDER BY created_at ASC, rowid ASC",
                (session_id,),
            ).fetchall()
        return [
            ChatMessage(
                message_id=r["message_id"],
                session_id=r["session_id"],
                role=r["role"],
                content=r["content"],
                tool_calls=json.loads(r["tool_calls_json"]) if r["tool_calls_json"] else [],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # ---- portfolio ----

    def save_portfolio(
        self, session_id: str, holdings: list[PortfolioHolding], source: str
    ) -> None:
        payload = [h.model_dump() for h in holdings]
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_portfolios (session_id, holdings_json, source, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "holdings_json=excluded.holdings_json, source=excluded.source, "
                "updated_at=excluded.updated_at",
                (session_id, _dumps(payload), source, _now()),
            )
            self._touch_session(conn, session_id)

    def get_portfolio(
        self, session_id: str
    ) -> tuple[list[PortfolioHolding], str | None]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT holdings_json, source FROM chat_portfolios WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if row is None:
            return [], None
        holdings = [PortfolioHolding(**h) for h in json.loads(row["holdings_json"])]
        return holdings, row["source"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/webui/test_chat_store.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add api/store.py tests/webui/test_chat_store.py
git commit -m "feat(advisor): add chat sessions/messages/portfolio store"
```

---

## Task 3: Advisor tools collection

**Files:**
- Create: `tradingagents/advisor/__init__.py`
- Create: `tradingagents/advisor/tools.py`
- Test: `tests/advisor/__init__.py`, `tests/advisor/test_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/advisor/test_tools.py
from tradingagents.advisor.tools import ADVISOR_TOOLS, is_no_data


def test_advisor_tools_are_langchain_tools():
    names = {t.name for t in ADVISOR_TOOLS}
    # core data tools the advisor exposes
    assert "get_stock_data" in names
    assert "get_news" in names
    assert "get_fundamentals" in names
    assert "get_indicators" in names


def test_is_no_data_detects_sentinels():
    assert is_no_data("NO_DATA_AVAILABLE: ticker not found")
    assert is_no_data("DATA_SOURCE_DISABLED: reddit off")
    assert not is_no_data("AAPL,2024-01-01,190.0,...")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/advisor/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.advisor'`

- [ ] **Step 3: Create the module files**

```python
# tradingagents/advisor/__init__.py
"""Investment-advisor chatbot engine (consumes finished reports + live data)."""
```

```python
# tests/advisor/__init__.py
```

```python
# tradingagents/advisor/tools.py
"""Live-data tools exposed to the advisor LLM (reused from agent_utils)."""

from tradingagents.agents.utils.agent_utils import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_global_news,
    get_income_statement,
    get_indicators,
    get_insider_transactions,
    get_macro_indicators,
    get_news,
    get_prediction_markets,
    get_stock_data,
)

# Tools the advisor may call during a conversation. These are already
# @tool-decorated LangChain tools that internally route through route_to_vendor
# and never raise (they return NO_DATA_AVAILABLE:/DATA_SOURCE_DISABLED: sentinels).
ADVISOR_TOOLS = [
    get_stock_data,
    get_indicators,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_news,
    get_global_news,
    get_insider_transactions,
    get_macro_indicators,
    get_prediction_markets,
]

_NO_DATA_PREFIXES = ("NO_DATA_AVAILABLE:", "DATA_SOURCE_DISABLED:")


def is_no_data(result: str) -> bool:
    """True if a tool return string is an unavailable-data sentinel."""
    return isinstance(result, str) and result.lstrip().startswith(_NO_DATA_PREFIXES)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/advisor/test_tools.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/advisor/__init__.py tradingagents/advisor/tools.py tests/advisor/__init__.py tests/advisor/test_tools.py
git commit -m "feat(advisor): collect dataflows tools for chat engine"
```

---

## Task 4: Report context assembler

**Files:**
- Create: `tradingagents/advisor/context.py`
- Test: `tests/advisor/test_context.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/advisor/test_context.py
from tradingagents.advisor.context import build_report_context


def test_build_report_context_includes_present_fields():
    result = {
        "market_report": "RSI 65, uptrend",
        "final_trade_decision": "**Rating**: Buy",
    }
    ctx = build_report_context(result, decision="Buy", ticker="AAPL")
    assert "AAPL" in ctx
    assert "Buy" in ctx
    assert "RSI 65" in ctx
    assert "市场分析" in ctx
    # absent fields are not rendered
    assert "新闻分析" not in ctx


def test_build_report_context_empty_result():
    ctx = build_report_context(None, decision=None, ticker="AAPL")
    assert "AAPL" in ctx
    assert "无可用报告" in ctx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/advisor/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.advisor.context'`

- [ ] **Step 3: Create `tradingagents/advisor/context.py`**

```python
# tradingagents/advisor/context.py
"""Assemble a completed analysis run's reports into LLM context text."""

# (field_key, human title) — mirrors api/routes/analysis.py:_REPORT_ORDER
_REPORT_ORDER = [
    ("market_report", "市场分析"),
    ("sentiment_report", "情绪分析"),
    ("news_report", "新闻分析"),
    ("fundamentals_report", "基本面分析"),
    ("investment_plan", "研究经理决策"),
    ("trader_investment_plan", "交易计划"),
    ("final_trade_decision", "组合经理最终决策"),
]


def build_report_context(
    result: dict | None, decision: str | None, ticker: str
) -> str:
    """Render the 7 report fields present in `result` into a markdown block."""
    parts = [f"# 标的 {ticker} 的 TradingAgents 分析报告"]
    if decision:
        parts.append(f"**最终评级: {decision}**")
    rendered_any = False
    if result:
        for key, title in _REPORT_ORDER:
            content = result.get(key)
            if content:
                rendered_any = True
                parts.append(f"\n## {title}\n\n{content}")
    if not rendered_any:
        parts.append("\n(无可用报告 — 用户尚未关联已完成的分析,或报告为空)")
    return "\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/advisor/test_context.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/advisor/context.py tests/advisor/test_context.py
git commit -m "feat(advisor): add report context assembler"
```

---

## Task 5: System prompt

**Files:**
- Create: `tradingagents/advisor/prompt.py`
- Test: `tests/advisor/test_prompt.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/advisor/test_prompt.py
from tradingagents.advisor.context import build_report_context
from tradingagents.advisor.prompt import build_system_prompt


def test_system_prompt_embeds_report_and_holdings():
    report_ctx = build_report_context(
        {"market_report": "uptrend"}, decision="Buy", ticker="AAPL"
    )
    holdings_ctx = "AAPL: 100 股, 占比 40%"
    prompt = build_system_prompt(report_ctx, holdings_ctx)
    assert "uptrend" in prompt
    assert "40%" in prompt
    # core behavioral constraints present
    assert "引用" in prompt  # citation rule
    assert "免责" in prompt or "投资建议" in prompt  # disclaimer
    assert "NO_DATA_AVAILABLE" in prompt  # honesty/no-fabrication rule


def test_system_prompt_handles_no_holdings():
    prompt = build_system_prompt("report", holdings_ctx="")
    assert "未提供持仓" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/advisor/test_prompt.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.advisor.prompt'`

- [ ] **Step 3: Create `tradingagents/advisor/prompt.py`**

```python
# tradingagents/advisor/prompt.py
"""System prompt for the investment-advisor chatbot."""

_TEMPLATE = """你是一名投资操作顾问。你的任务是基于下方的 TradingAgents 分析报告、\
用户的当前持仓,以及在需要时通过工具实时查询的市场数据,给出具体、可执行的操作建议与解释。

# 行为准则(强约束)
1. 引用依据:每条建议都必须注明依据 —— 引用具体分析师/角色(如"看跌研究员指出…"\
"组合经理评级为…")、具体报告字段,或实时工具返回的数据。禁止脱离报告与数据凭空给建议。
2. 持仓感知:结合用户的实际仓位给出相对建议(如"AAPL 占组合 40%,集中度偏高,可考虑减至 25%"),\
不要泛泛而谈。
3. 诚实约束:当工具返回以 NO_DATA_AVAILABLE: 或 DATA_SOURCE_DISABLED: 开头的字符串时,\
说明该数据不可用,绝不编造价格、点位或数字。
4. 免责声明:在会话的首条回复,以及每条明确的操作建议之后,附上"以上为基于研究的分析,\
不构成投资建议"的提示。

# 可用实时数据工具
当报告中的数据不足以回答用户问题时,你可以调用工具获取实时价格、技术指标、新闻、\
基本面、宏观指标等。优先使用报告中已有的信息,仅在确有必要时调用工具。

# 分析报告上下文
{report_context}

# 用户当前持仓
{holdings_context}
"""

_NO_HOLDINGS = "用户未提供持仓信息。可建议用户上传持仓截图,或在不依赖具体仓位的前提下给出一般性分析。"


def build_system_prompt(report_context: str, holdings_ctx: str) -> str:
    holdings = holdings_ctx.strip() if holdings_ctx and holdings_ctx.strip() else _NO_HOLDINGS
    return _TEMPLATE.format(report_context=report_context, holdings_context=holdings)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/advisor/test_prompt.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/advisor/prompt.py tests/advisor/test_prompt.py
git commit -m "feat(advisor): add advisor system prompt"
```

---

## Task 6: Vision portfolio extraction

**Files:**
- Create: `tradingagents/advisor/vision.py`
- Test: `tests/advisor/test_vision.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/advisor/test_vision.py
import base64
import json

from langchain_core.messages import AIMessage

from tradingagents.advisor.vision import (
    build_vision_message,
    extract_holdings,
    parse_holdings_json,
)


class _FakeVisionLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, messages):
        return AIMessage(content=self._content)


def test_build_vision_message_has_image_and_text():
    msg = build_vision_message(b"\x89PNG\r\n", mime="image/png")
    blocks = msg.content
    types = {b["type"] for b in blocks}
    assert types == {"image_url", "text"}
    img = next(b for b in blocks if b["type"] == "image_url")
    assert img["image_url"]["url"].startswith("data:image/png;base64,")
    decoded = base64.b64decode(img["image_url"]["url"].split(",", 1)[1])
    assert decoded == b"\x89PNG\r\n"


def test_parse_holdings_json_plain_array():
    raw = json.dumps([{"ticker": "AAPL", "shares": 10, "weight": 40}])
    holdings = parse_holdings_json(raw)
    assert holdings[0].ticker == "AAPL"
    assert holdings[0].shares == 10


def test_parse_holdings_json_fenced_code_block():
    raw = "```json\n[{\"ticker\": \"MSFT\"}]\n```"
    holdings = parse_holdings_json(raw)
    assert holdings[0].ticker == "MSFT"


def test_parse_holdings_json_unparseable_returns_empty():
    assert parse_holdings_json("sorry, I can't read this image") == []


def test_extract_holdings_uses_llm(monkeypatch):
    llm = _FakeVisionLLM(json.dumps([{"ticker": "AAPL", "shares": 5}]))
    holdings = extract_holdings(llm, b"img", mime="image/png")
    assert holdings[0].ticker == "AAPL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/advisor/test_vision.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.advisor.vision'`

- [ ] **Step 3: Create `tradingagents/advisor/vision.py`**

```python
# tradingagents/advisor/vision.py
"""Extract structured portfolio holdings from an uploaded screenshot."""

import base64
import json
import re

from langchain_core.messages import HumanMessage

from api.schemas import PortfolioHolding

_EXTRACT_INSTRUCTION = (
    "这是一张投资组合 / 交易记录截图。请提取其中的持仓与交易记录,"
    "输出一个 JSON 数组,每个元素包含可识别到的字段:"
    "ticker(代码)、name(名称)、shares(股数)、avg_cost(成本价)、"
    "market_value(市值)、weight(占比百分比数值)、action(buy/sell,若为交易记录)、"
    "trade_date(交易日期)。无法识别的字段省略或设为 null。"
    "只输出 JSON 数组,不要其它文字。若无法识别任何持仓,输出空数组 []。"
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def build_vision_message(image_bytes: bytes, mime: str = "image/png") -> HumanMessage:
    b64 = base64.b64encode(image_bytes).decode()
    return HumanMessage(
        content=[
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text", "text": _EXTRACT_INSTRUCTION},
        ]
    )


def parse_holdings_json(raw: str) -> list[PortfolioHolding]:
    """Parse the LLM's JSON reply; tolerate code fences; return [] on failure."""
    text = raw.strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    holdings: list[PortfolioHolding] = []
    for item in data:
        if not isinstance(item, dict) or not item.get("ticker"):
            continue
        try:
            holdings.append(PortfolioHolding(**item))
        except Exception:  # noqa: BLE001 — skip malformed rows, never fabricate
            continue
    return holdings


def extract_holdings(llm, image_bytes: bytes, mime: str = "image/png") -> list[PortfolioHolding]:
    """Send the screenshot to a vision LLM and parse the structured reply."""
    msg = build_vision_message(image_bytes, mime=mime)
    response = llm.invoke([msg])
    content = response.content
    if isinstance(content, list):  # some providers return content blocks
        content = " ".join(
            b.get("text", "") for b in content if isinstance(b, dict)
        )
    return parse_holdings_json(content)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/advisor/test_vision.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/advisor/vision.py tests/advisor/test_vision.py
git commit -m "feat(advisor): add vision portfolio extraction"
```

---

## Task 7: Conversation engine (tool loop → SSE events)

**Files:**
- Create: `tradingagents/advisor/engine.py`
- Test: `tests/advisor/test_engine.py`

The engine runs the tool-call loop and yields event dicts of shape `{"event": str, "data": dict}` — the same shape the SSE route consumes. It is sync (called inside the route's background thread).

- [ ] **Step 1: Write the failing test**

```python
# tests/advisor/test_engine.py
from langchain_core.messages import AIMessage

from tradingagents.advisor.engine import run_chat


class _FakeChain:
    """Returns a scripted sequence of AIMessages on successive invokes."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.invocations = []

    def invoke(self, messages):
        self.invocations.append(messages)
        return self._responses.pop(0)


class _FakeBindable:
    """Stands in for `llm`; `prompt | llm.bind_tools(tools)` returns a chain."""

    def __init__(self, chain):
        self._chain = chain

    def bind_tools(self, tools):
        return self  # we ignore prompt-piping in the test by patching builder

    def __ror__(self, other):  # prompt | self
        return self._chain


def test_run_chat_streams_tokens_when_no_tool_calls():
    chain = _FakeChain([AIMessage(content="持仓集中度偏高。不构成投资建议。")])
    events = list(
        run_chat(
            chain=chain,
            history_messages=[],
            user_message="该减仓吗?",
            tools_by_name={},
        )
    )
    kinds = [e["event"] for e in events]
    assert kinds[-1] == "done"
    token_text = "".join(
        e["data"]["content"] for e in events if e["event"] == "token"
    )
    assert "持仓集中度偏高" in token_text


def test_run_chat_executes_tool_then_answers():
    ai_with_tool = AIMessage(
        content="",
        tool_calls=[
            {"name": "get_stock_data", "args": {"symbol": "AAPL"}, "id": "tc1"}
        ],
    )
    ai_final = AIMessage(content="当前价已确认。不构成投资建议。")
    chain = _FakeChain([ai_with_tool, ai_final])

    def fake_tool(**kwargs):
        return "AAPL,2024-01-01,190.0"

    events = list(
        run_chat(
            chain=chain,
            history_messages=[],
            user_message="现在多少钱?",
            tools_by_name={"get_stock_data": fake_tool},
        )
    )
    kinds = [e["event"] for e in events]
    assert "tool_call" in kinds
    assert kinds[-1] == "done"
    tool_event = next(e for e in events if e["event"] == "tool_call")
    assert tool_event["data"]["tool"] == "get_stock_data"
    # final answer text streamed
    text = "".join(e["data"]["content"] for e in events if e["event"] == "token")
    assert "已确认" in text


def test_run_chat_done_carries_full_text_and_tool_calls():
    ai_with_tool = AIMessage(
        content="",
        tool_calls=[{"name": "get_news", "args": {"ticker": "AAPL"}, "id": "t1"}],
    )
    ai_final = AIMessage(content="结论。")
    chain = _FakeChain([ai_with_tool, ai_final])
    events = list(
        run_chat(
            chain=chain,
            history_messages=[],
            user_message="新闻?",
            tools_by_name={"get_news": lambda **k: "headline"},
        )
    )
    done = events[-1]
    assert done["event"] == "done"
    assert done["data"]["content"] == "结论。"
    assert done["data"]["tool_calls"][0]["tool"] == "get_news"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/advisor/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.advisor.engine'`

- [ ] **Step 3: Create `tradingagents/advisor/engine.py`**

```python
# tradingagents/advisor/engine.py
"""Conversation engine: tool-call loop yielding SSE-shaped event dicts."""

from collections.abc import Iterator

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tradingagents.advisor.tools import is_no_data

_MAX_TOOL_ROUNDS = 6


def run_chat(
    chain,
    history_messages: list,
    user_message: str,
    tools_by_name: dict,
) -> Iterator[dict]:
    """Drive the tool-call loop.

    `chain` is `prompt | llm.bind_tools(tools)` and is invoked with a message
    list. Yields dicts: {"event": "tool_call"|"token"|"done"|"error", "data": {...}}.
    """
    messages = list(history_messages) + [HumanMessage(content=user_message)]
    executed_tool_calls: list[dict] = []

    try:
        result: AIMessage = chain.invoke(messages)
        rounds = 0
        while getattr(result, "tool_calls", None) and rounds < _MAX_TOOL_ROUNDS:
            rounds += 1
            messages.append(result)
            for call in result.tool_calls:
                name = call["name"]
                args = call.get("args", {})
                yield {"event": "tool_call", "data": {"tool": name, "args": args}}
                tool = tools_by_name.get(name)
                if tool is None:
                    output = f"NO_DATA_AVAILABLE: unknown tool {name}"
                else:
                    try:
                        output = tool(**args)
                    except Exception as exc:  # noqa: BLE001
                        output = f"NO_DATA_AVAILABLE: tool error: {exc}"
                executed_tool_calls.append(
                    {"tool": name, "args": args, "unavailable": is_no_data(output)}
                )
                messages.append(
                    ToolMessage(content=str(output), tool_call_id=call.get("id", name))
                )
            result = chain.invoke(messages)

        text = result.content if isinstance(result.content, str) else str(result.content)
        # Stream the final answer token-ish (chunk by characters in fixed sizes).
        for i in range(0, len(text), 24):
            yield {"event": "token", "data": {"content": text[i : i + 24]}}

        yield {
            "event": "done",
            "data": {"content": text, "tool_calls": executed_tool_calls},
        }
    except Exception as exc:  # noqa: BLE001
        yield {"event": "error", "data": {"message": str(exc)}}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/advisor/test_engine.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/advisor/engine.py tests/advisor/test_engine.py
git commit -m "feat(advisor): add conversation tool-loop engine"
```

---

## Task 8: Chat LLM factory + wiring in main.py

**Files:**
- Modify: `api/main.py`
- Test: covered by Task 9 route tests (factory injection)

- [ ] **Step 1: Add factory + state field to `api/main.py`**

Add `app.state.chat_llm_factory = None` to the state block (after line 36 `app.state.graph_factory = None`):

```python
app.state.chat_llm_factory = None  # set at startup; tests inject their own
```

Register the chat router after the analysis router (after line 53):

```python
from api.routes import chat as chat_routes  # noqa: E402

app.include_router(chat_routes.router)
```

Add the real factory function (after `real_graph_factory`, before the startup hook at line 96). It returns a `(chat_llm, vision_llm)` pair built from `DEFAULT_CONFIG`:

```python
def real_chat_llm_factory():
    """Build (chat_llm, vision_llm) LangChain models from DEFAULT_CONFIG.

    Both use the configured provider/model. The vision model must support image
    input (anthropic / google / openai families). set_config() makes the
    dataflows vendor routing match the configured data_vendors.
    """
    from tradingagents.dataflows.config import set_config
    from tradingagents.llm_clients import create_llm_client

    config = DEFAULT_CONFIG.copy()
    set_config(config)

    provider = config["llm_provider"]
    model = config["quick_think_llm"]
    base_url = config.get("backend_url")

    client = create_llm_client(provider=provider, model=model, base_url=base_url)
    chat_llm = client.get_llm()
    # Same model handles vision for Claude/Gemini/GPT families.
    vision_llm = chat_llm
    return chat_llm, vision_llm
```

Extend the startup hook (currently lines 96-99) to also wire the chat factory:

```python
@app.on_event("startup")
def _wire_graph_factory():
    if app.state.graph_factory is None:
        app.state.graph_factory = real_graph_factory
    if app.state.chat_llm_factory is None:
        app.state.chat_llm_factory = real_chat_llm_factory
```

- [ ] **Step 2: Verify import does not crash**

Run: `python -c "import api.main"`
Expected: no output, exit 0. (Will fail until Task 9 creates `api/routes/chat.py` — that's expected; do Task 9 next, then re-run.)

- [ ] **Step 3: Commit (after Task 9 makes the import resolve)**

Defer the commit to the end of Task 9 so the chat router import resolves. (No standalone commit here.)

---

## Task 9: Chat routes (CRUD + portfolio + SSE stream)

**Files:**
- Create: `api/routes/chat.py`
- Modify: `tests/webui/conftest.py` (reset `chat_llm_factory` in the `client` fixture)
- Test: `tests/webui/test_routes_chat.py`

- [ ] **Step 1: Update the `client` fixture in `tests/webui/conftest.py`**

Add a reset for the chat factory inside the fixture (after line 15 `main.app.state.starting_telemetry = None`):

```python
    main.app.state.chat_llm_factory = None
```

- [ ] **Step 2: Write the failing test**

```python
# tests/webui/test_routes_chat.py
import json

from langchain_core.messages import AIMessage


def _install_fake_chat(client, chat_responses, vision_content="[]"):
    import api.main as main

    class _FakeChain:
        def __init__(self, responses):
            self._responses = list(responses)

        def invoke(self, messages):
            return self._responses.pop(0)

    class _FakeLLM:
        def __init__(self, chain, vision_content):
            self._chain = chain
            self._vision_content = vision_content

        def bind_tools(self, tools):
            return self._chain

        def invoke(self, messages):  # vision path
            return AIMessage(content=self._vision_content)

    def factory():
        chain = _FakeChain(chat_responses)
        llm = _FakeLLM(chain, vision_content)
        # chat_llm must support `prompt | llm.bind_tools(tools)`: bind_tools
        # returns the chain directly, and the route builds the chain from it.
        return llm, llm

    main.app.state.chat_llm_factory = factory


def test_create_and_get_session(client):
    _install_fake_chat(client, [])
    resp = client.post("/api/chat/sessions", json={"run_id": None})
    assert resp.status_code == 200
    sid = resp.json()["session_id"]

    detail = client.get(f"/api/chat/sessions/{sid}")
    assert detail.status_code == 200
    assert detail.json()["session"]["session_id"] == sid
    assert detail.json()["messages"] == []


def test_list_sessions(client):
    _install_fake_chat(client, [])
    client.post("/api/chat/sessions", json={})
    resp = client.get("/api/chat/sessions")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_delete_session(client):
    _install_fake_chat(client, [])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    assert client.delete(f"/api/chat/sessions/{sid}").status_code == 200
    assert client.get(f"/api/chat/sessions/{sid}").status_code == 404


def test_stream_chat_emits_done_and_persists(client):
    _install_fake_chat(client, [AIMessage(content="结论。不构成投资建议。")])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]

    with client.stream(
        "POST", f"/api/chat/sessions/{sid}/stream", json={"message": "该减仓吗?"}
    ) as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "event: token" in body
    assert "event: done" in body

    msgs = client.get(f"/api/chat/sessions/{sid}").json()["messages"]
    roles = [m["role"] for m in msgs]
    assert roles == ["user", "assistant"]
    assert "结论" in msgs[1]["content"]


def test_portfolio_extract_and_get(client):
    _install_fake_chat(
        client,
        [],
        vision_content=json.dumps([{"ticker": "AAPL", "shares": 10, "weight": 40}]),
    )
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]

    resp = client.post(
        f"/api/chat/sessions/{sid}/portfolio",
        files={"file": ("p.png", b"\x89PNG", "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["holdings"][0]["ticker"] == "AAPL"
    assert resp.json()["source"] == "vision"

    got = client.get(f"/api/chat/sessions/{sid}/portfolio")
    assert got.json()["holdings"][0]["ticker"] == "AAPL"


def test_portfolio_manual_overwrite(client):
    _install_fake_chat(client, [])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    resp = client.put(
        f"/api/chat/sessions/{sid}/portfolio",
        json={"holdings": [{"ticker": "MSFT", "shares": 5}], "source": "manual"},
    )
    assert resp.status_code == 200
    got = client.get(f"/api/chat/sessions/{sid}/portfolio")
    assert got.json()["holdings"][0]["ticker"] == "MSFT"
    assert got.json()["source"] == "manual"


def test_chat_does_not_trigger_409_when_analysis_running(client, monkeypatch):
    import api.main as main

    monkeypatch.setattr(main.get_store(), "has_running_run", lambda: True)
    _install_fake_chat(client, [AIMessage(content="ok。不构成投资建议。")])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    # session creation and streaming both succeed despite a running analysis
    with client.stream(
        "POST", f"/api/chat/sessions/{sid}/stream", json={"message": "hi"}
    ) as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "event: done" in body


def test_stream_unknown_session_404(client):
    _install_fake_chat(client, [])
    resp = client.post(
        "/api/chat/sessions/nope/stream", json={"message": "hi"}
    )
    assert resp.status_code == 404
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/webui/test_routes_chat.py -v`
Expected: FAIL — `api/routes/chat.py` does not exist yet (import error at collection).

- [ ] **Step 4: Create `api/routes/chat.py`**

```python
# api/routes/chat.py
"""Chat routes: session CRUD, portfolio extraction, SSE token streaming."""

import queue
import threading
import uuid

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from sse_starlette.sse import EventSourceResponse

from api.schemas import (
    ChatSessionCreate,
    PortfolioExtractResponse,
    PortfolioHolding,
)
from tradingagents.advisor.context import build_report_context
from tradingagents.advisor.engine import run_chat
from tradingagents.advisor.prompt import build_system_prompt
from tradingagents.advisor.tools import ADVISOR_TOOLS

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _holdings_text(holdings: list[PortfolioHolding]) -> str:
    if not holdings:
        return ""
    lines = []
    for h in holdings:
        bits = [h.ticker]
        if h.shares is not None:
            bits.append(f"{h.shares} 股")
        if h.weight is not None:
            bits.append(f"占比 {h.weight}%")
        if h.avg_cost is not None:
            bits.append(f"成本 {h.avg_cost}")
        if h.market_value is not None:
            bits.append(f"市值 {h.market_value}")
        if h.action is not None:
            bits.append(f"操作 {h.action}")
        lines.append(": ".join([bits[0], ", ".join(bits[1:])]) if len(bits) > 1 else bits[0])
    return "\n".join(lines)


@router.post("/sessions")
def create_session(req: ChatSessionCreate, request: Request) -> dict:
    from api.main import get_store

    store = get_store()
    title = None
    if req.run_id:
        run = store.get_run(req.run_id)
        if run is not None:
            title = f"{run.ticker} ({run.trade_date})"
    session_id = uuid.uuid4().hex
    store.create_chat_session(session_id, run_id=req.run_id, title=title)
    return {"session_id": session_id}


@router.get("/sessions")
def list_sessions() -> list[dict]:
    from api.main import get_store

    return [s.model_dump() for s in get_store().list_chat_sessions()]


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    from api.main import get_store

    store = get_store()
    session = store.get_chat_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    messages = store.list_chat_messages(session_id)
    return {
        "session": session.model_dump(),
        "messages": [m.model_dump() for m in messages],
    }


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    from api.main import get_store

    store = get_store()
    if store.get_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    store.delete_chat_session(session_id)
    return {"session_id": session_id, "status": "deleted"}


@router.post("/sessions/{session_id}/portfolio", response_model=PortfolioExtractResponse)
async def extract_portfolio(
    session_id: str, request: Request, file: UploadFile = File(...)
) -> PortfolioExtractResponse:
    from api.main import get_store
    from tradingagents.advisor.vision import extract_holdings

    store = get_store()
    if store.get_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")

    image_bytes = await file.read()
    _, vision_llm = request.app.state.chat_llm_factory()
    holdings = extract_holdings(
        vision_llm, image_bytes, mime=file.content_type or "image/png"
    )
    store.save_portfolio(session_id, holdings, source="vision")
    return PortfolioExtractResponse(holdings=holdings, source="vision")


@router.put("/sessions/{session_id}/portfolio", response_model=PortfolioExtractResponse)
def save_portfolio(
    session_id: str, payload: PortfolioExtractResponse
) -> PortfolioExtractResponse:
    from api.main import get_store

    store = get_store()
    if store.get_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    store.save_portfolio(session_id, payload.holdings, source="manual")
    return PortfolioExtractResponse(holdings=payload.holdings, source="manual")


@router.get("/sessions/{session_id}/portfolio", response_model=PortfolioExtractResponse)
def get_portfolio(session_id: str) -> PortfolioExtractResponse:
    from api.main import get_store

    store = get_store()
    if store.get_chat_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    holdings, source = store.get_portfolio(session_id)
    return PortfolioExtractResponse(holdings=holdings, source=source or "manual")


@router.post("/sessions/{session_id}/stream")
async def stream_chat(
    session_id: str, req_body: dict, request: Request
) -> EventSourceResponse:
    from api.main import get_store

    store = get_store()
    session = store.get_chat_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    user_message = req_body.get("message", "")

    # Build report + holdings context.
    report_ctx = ""
    decision = None
    ticker = "标的"
    if session.run_id:
        run = store.get_run(session.run_id)
        if run is not None:
            decision = run.decision
            ticker = run.ticker
            report_ctx = build_report_context(run.result, decision, ticker)
    else:
        report_ctx = build_report_context(None, None, ticker)

    holdings, _ = store.get_portfolio(session_id)
    holdings_ctx = _holdings_text(holdings)
    system_prompt = build_system_prompt(report_ctx, holdings_ctx)

    # Prior conversation as LangChain messages.
    history = []
    for m in store.list_chat_messages(session_id):
        if m.role == "user":
            history.append(HumanMessage(content=m.content))
        else:
            history.append(AIMessage(content=m.content))

    chat_llm, _ = request.app.state.chat_llm_factory()
    prompt = ChatPromptTemplate.from_messages(
        [("system", "{system}"), MessagesPlaceholder(variable_name="messages")]
    ).partial(system=system_prompt)
    chain = prompt | chat_llm.bind_tools(ADVISOR_TOOLS)

    tools_by_name = {t.name: t for t in ADVISOR_TOOLS}

    # Persist the user message now.
    store.insert_chat_message(
        uuid.uuid4().hex, session_id, "user", user_message, tool_calls=[]
    )

    q: queue.Queue = queue.Queue()

    def _worker():
        final_text = ""
        final_tool_calls: list[dict] = []
        try:
            for event in run_chat(
                chain=chain,
                history_messages=history,
                user_message=user_message,
                tools_by_name=tools_by_name,
            ):
                if event["event"] == "done":
                    final_text = event["data"]["content"]
                    final_tool_calls = event["data"]["tool_calls"]
                q.put(event)
        finally:
            if final_text:
                store.insert_chat_message(
                    uuid.uuid4().hex,
                    session_id,
                    "assistant",
                    final_text,
                    tool_calls=final_tool_calls,
                )
            q.put(None)  # sentinel

    threading.Thread(target=_worker, daemon=True).start()

    async def event_generator():
        import asyncio
        import json

        while True:
            try:
                item = await asyncio.to_thread(q.get, True, 1.0)
            except queue.Empty:
                if await request.is_disconnected():
                    break
                continue
            if item is None:
                break
            yield {"event": item["event"], "data": json.dumps(item["data"])}

    return EventSourceResponse(event_generator())
```

Note on the test fake: in `_install_fake_chat`, `bind_tools()` returns the `_FakeChain`, and `prompt | chain` works because LangChain's `prompt.__or__` wraps any runnable; the fake chain's `.invoke(messages)` receives the formatted prompt value. If the prompt-piping interferes in practice, the route still calls `.invoke` on the piped runnable — the fake's `invoke` returns the scripted `AIMessage`. Keep the fake chain's `invoke` signature accepting a single positional arg.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/webui/test_routes_chat.py -v`
Expected: PASS (8 passed)

- [ ] **Step 6: Verify main imports and full backend suite**

Run: `python -c "import api.main" && pytest tests/webui tests/advisor -m unit -q`
Expected: import OK; all tests pass.

- [ ] **Step 7: Lint**

Run: `ruff check api/ tradingagents/advisor/ tests/advisor/ tests/webui/test_chat_store.py tests/webui/test_chat_schemas.py tests/webui/test_routes_chat.py`
Expected: no errors (E501 is ignored per project config).

- [ ] **Step 8: Commit**

```bash
git add api/main.py api/routes/chat.py tests/webui/conftest.py tests/webui/test_routes_chat.py
git commit -m "feat(advisor): add chat routes with SSE streaming and portfolio upload"
```

---

## Task 10: Frontend — types, API client, SSE subscription

**Files:**
- Modify: `webui/lib/types.ts`
- Modify: `webui/lib/api.ts`
- Modify: `webui/lib/sse.ts`

> **Next.js 16 note:** before editing frontend code, read the relevant guide under `webui/node_modules/next/dist/docs/` (per `webui/AGENTS.md`). The patterns below match the existing `webui/lib/*` conventions; verify `EventSource`/fetch usage hasn't changed.

- [ ] **Step 1: Add chat types to `webui/lib/types.ts`**

Append (match existing type style in the file):

```typescript
export interface PortfolioHolding {
  ticker: string;
  name?: string | null;
  shares?: number | null;
  avg_cost?: number | null;
  market_value?: number | null;
  weight?: number | null;
  action?: "buy" | "sell" | null;
  trade_date?: string | null;
}

export interface ChatMessageT {
  message_id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  tool_calls: Record<string, unknown>[];
  created_at: string;
}

export interface ChatSessionT {
  session_id: string;
  run_id: string | null;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export type ChatSSEEvent =
  | { event: "tool_call"; data: { tool: string; args: Record<string, unknown> } }
  | { event: "token"; data: { content: string } }
  | { event: "done"; data: { content: string; tool_calls: Record<string, unknown>[] } }
  | { event: "error"; data: { message: string } };
```

- [ ] **Step 2: Add chat API calls to `webui/lib/api.ts`**

Append, reusing the existing `BASE` constant already defined in the file:

```typescript
import type {
  ChatSessionT,
  ChatMessageT,
  PortfolioHolding,
} from "./types";

export async function createChatSession(runId: string | null): Promise<string> {
  const r = await fetch(`${BASE}/api/chat/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId }),
  });
  return (await r.json()).session_id as string;
}

export async function listChatSessions(): Promise<ChatSessionT[]> {
  const r = await fetch(`${BASE}/api/chat/sessions`);
  return r.json();
}

export async function getChatSession(
  id: string,
): Promise<{ session: ChatSessionT; messages: ChatMessageT[] }> {
  const r = await fetch(`${BASE}/api/chat/sessions/${id}`);
  if (!r.ok) throw new Error("session not found");
  return r.json();
}

export async function deleteChatSession(id: string): Promise<void> {
  await fetch(`${BASE}/api/chat/sessions/${id}`, { method: "DELETE" });
}

export async function uploadPortfolio(
  id: string,
  file: File,
): Promise<{ holdings: PortfolioHolding[]; source: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${BASE}/api/chat/sessions/${id}/portfolio`, {
    method: "POST",
    body: fd,
  });
  return r.json();
}

export async function savePortfolio(
  id: string,
  holdings: PortfolioHolding[],
): Promise<{ holdings: PortfolioHolding[]; source: string }> {
  const r = await fetch(`${BASE}/api/chat/sessions/${id}/portfolio`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ holdings, source: "manual" }),
  });
  return r.json();
}

export async function getPortfolio(
  id: string,
): Promise<{ holdings: PortfolioHolding[]; source: string }> {
  const r = await fetch(`${BASE}/api/chat/sessions/${id}/portfolio`);
  return r.json();
}

export function chatStreamUrl(id: string): string {
  return `${BASE}/api/chat/sessions/${id}/stream`;
}
```

- [ ] **Step 3: Add a POST-based SSE reader to `webui/lib/sse.ts`**

The existing `subscribe()` uses `EventSource` (GET only). Chat streaming is POST, so add a fetch-stream reader. Append:

```typescript
import type { ChatSSEEvent } from "./types";

/**
 * POST a chat message and stream SSE events back via fetch + ReadableStream.
 * Native EventSource cannot POST, so we parse the SSE wire format manually.
 */
export async function streamChat(
  url: string,
  message: string,
  onEvent: (e: ChatSSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    signal,
  });
  if (!resp.body) return;
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      let eventName = "message";
      let dataLine = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLine += line.slice(5).trim();
      }
      if (!dataLine) continue;
      try {
        onEvent({ event: eventName, data: JSON.parse(dataLine) } as ChatSSEEvent);
      } catch {
        /* ignore malformed block */
      }
    }
  }
}
```

- [ ] **Step 4: Type-check the frontend**

Run: `cd webui && npx tsc --noEmit`
Expected: no type errors.

- [ ] **Step 5: Commit**

```bash
git add webui/lib/types.ts webui/lib/api.ts webui/lib/sse.ts
git commit -m "feat(advisor): add chat frontend api client and sse reader"
```

---

## Task 11: Frontend — chat components

**Files:**
- Create: `webui/components/chat/RunPicker.tsx`
- Create: `webui/components/chat/PortfolioUpload.tsx`
- Create: `webui/components/chat/HoldingsTable.tsx`
- Create: `webui/components/chat/ChatMessage.tsx`

> Use existing primitives: `Button` from `webui/components/ui/button`, `cn` from `webui/lib/utils`, `MarkdownContent` from `webui/components/MarkdownContent`, icons from `lucide-react`. Cards use the established pattern: `rounded-lg border border-border bg-card`. Do NOT introduce standard shadcn/Radix components.

- [ ] **Step 1: Create `RunPicker.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { getHistory } from "@/lib/api"; // existing history fetch
import type { HistorySummary } from "@/lib/types"; // existing type

export function RunPicker({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (runId: string | null) => void;
}) {
  const [runs, setRuns] = useState<HistorySummary[]>([]);
  useEffect(() => {
    getHistory()
      .then((rs) => setRuns(rs.filter((r) => r.status === "completed")))
      .catch(() => setRuns([]));
  }, []);
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-3">
      <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
        关联分析报告
      </div>
      <select
        className="mt-2 w-full rounded-md border border-border bg-background px-2 py-1 text-sm"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">不关联(通用咨询)</option>
        {runs.map((r) => (
          <option key={r.run_id} value={r.run_id}>
            {r.ticker} · {r.trade_date} · {r.decision ?? "—"}
          </option>
        ))}
      </select>
    </div>
  );
}
```

> If `getHistory`/`HistorySummary` names differ in the existing `webui/lib/api.ts`/`types.ts`, use the actual exported names — grep the file first.

- [ ] **Step 2: Create `HoldingsTable.tsx`**

```tsx
"use client";

import type { PortfolioHolding } from "@/lib/types";

export function HoldingsTable({
  holdings,
  onChange,
}: {
  holdings: PortfolioHolding[];
  onChange: (next: PortfolioHolding[]) => void;
}) {
  if (holdings.length === 0) {
    return (
      <div className="text-sm text-muted-foreground">尚无持仓。上传截图或手动添加。</div>
    );
  }
  const update = (i: number, field: keyof PortfolioHolding, raw: string) => {
    const next = [...holdings];
    const numeric = ["shares", "avg_cost", "market_value", "weight"];
    next[i] = {
      ...next[i],
      [field]: numeric.includes(field) ? (raw === "" ? null : Number(raw)) : raw,
    };
    onChange(next);
  };
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="font-mono text-[0.65rem] uppercase text-muted-foreground">
          <th className="text-left">代码</th>
          <th className="text-left">股数</th>
          <th className="text-left">成本</th>
          <th className="text-left">占比%</th>
        </tr>
      </thead>
      <tbody>
        {holdings.map((h, i) => (
          <tr key={i} className="border-t border-border">
            <td><input className="w-full bg-transparent" value={h.ticker} onChange={(e) => update(i, "ticker", e.target.value)} /></td>
            <td><input className="w-full bg-transparent" value={h.shares ?? ""} onChange={(e) => update(i, "shares", e.target.value)} /></td>
            <td><input className="w-full bg-transparent" value={h.avg_cost ?? ""} onChange={(e) => update(i, "avg_cost", e.target.value)} /></td>
            <td><input className="w-full bg-transparent" value={h.weight ?? ""} onChange={(e) => update(i, "weight", e.target.value)} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 3: Create `PortfolioUpload.tsx`**

```tsx
"use client";

import { useState } from "react";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { uploadPortfolio } from "@/lib/api";
import type { PortfolioHolding } from "@/lib/types";

export function PortfolioUpload({
  sessionId,
  onExtracted,
}: {
  sessionId: string;
  onExtracted: (holdings: PortfolioHolding[]) => void;
}) {
  const [busy, setBusy] = useState(false);
  const handle = async (file: File) => {
    setBusy(true);
    try {
      const res = await uploadPortfolio(sessionId, file);
      onExtracted(res.holdings);
    } finally {
      setBusy(false);
    }
  };
  return (
    <label className="inline-flex">
      <input
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => e.target.files?.[0] && handle(e.target.files[0])}
      />
      <Button asChild disabled={busy} variant="outline">
        <span className="inline-flex items-center gap-2">
          <Upload className="h-4 w-4" />
          {busy ? "识别中…" : "上传持仓截图"}
        </span>
      </Button>
    </label>
  );
}
```

> Verify `Button`'s `asChild`/`variant` props exist in the base-nova `webui/components/ui/button.tsx`. If `asChild` is unavailable, wrap the input+span directly without `asChild`.

- [ ] **Step 4: Create `ChatMessage.tsx`**

```tsx
"use client";

import { cn } from "@/lib/utils";
import { MarkdownContent } from "@/components/MarkdownContent";
import type { ChatMessageT } from "@/lib/types";

export function ChatMessage({ message }: { message: ChatMessageT }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[80%] rounded-lg border border-border px-3 py-2",
          isUser ? "bg-primary/10" : "bg-card",
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap text-sm">{message.content}</p>
        ) : (
          <MarkdownContent content={message.content} />
        )}
        {message.tool_calls?.length > 0 && (
          <div className="mt-1 font-mono text-[0.6rem] text-muted-foreground">
            数据来源: {message.tool_calls.map((t: any) => t.tool).join(", ")}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Type-check**

Run: `cd webui && npx tsc --noEmit`
Expected: no type errors. (Fix any name mismatches against actual existing exports.)

- [ ] **Step 6: Commit**

```bash
git add webui/components/chat/
git commit -m "feat(advisor): add chat ui components"
```

---

## Task 12: Frontend — chat page

**Files:**
- Create: `webui/app/chat/page.tsx`

- [ ] **Step 1: Create `webui/app/chat/page.tsx`**

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  createChatSession,
  getChatSession,
  getPortfolio,
  savePortfolio,
  chatStreamUrl,
} from "@/lib/api";
import { streamChat } from "@/lib/sse";
import type { ChatMessageT, PortfolioHolding } from "@/lib/types";
import { RunPicker } from "@/components/chat/RunPicker";
import { PortfolioUpload } from "@/components/chat/PortfolioUpload";
import { HoldingsTable } from "@/components/chat/HoldingsTable";
import { ChatMessage } from "@/components/chat/ChatMessage";

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessageT[]>([]);
  const [holdings, setHoldings] = useState<PortfolioHolding[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const streamingRef = useRef("");

  // Create a session on mount (or when runId changes).
  useEffect(() => {
    createChatSession(runId).then((sid) => {
      setSessionId(sid);
      setMessages([]);
      getPortfolio(sid).then((p) => setHoldings(p.holdings));
    });
  }, [runId]);

  const send = async () => {
    if (!sessionId || !input.trim() || streaming) return;
    const userMsg: ChatMessageT = {
      message_id: `local-${Date.now()}`,
      session_id: sessionId,
      role: "user",
      content: input,
      tool_calls: [],
      created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, userMsg]);
    const question = input;
    setInput("");
    setStreaming(true);
    streamingRef.current = "";

    const assistantId = `stream-${Date.now()}`;
    setMessages((m) => [
      ...m,
      { message_id: assistantId, session_id: sessionId, role: "assistant", content: "", tool_calls: [], created_at: new Date().toISOString() },
    ]);

    await streamChat(chatStreamUrl(sessionId), question, (e) => {
      if (e.event === "token") {
        streamingRef.current += e.data.content;
        setMessages((m) =>
          m.map((msg) =>
            msg.message_id === assistantId
              ? { ...msg, content: streamingRef.current }
              : msg,
          ),
        );
      } else if (e.event === "done") {
        setMessages((m) =>
          m.map((msg) =>
            msg.message_id === assistantId
              ? { ...msg, content: e.data.content, tool_calls: e.data.tool_calls }
              : msg,
          ),
        );
      }
    });
    setStreaming(false);
  };

  const persistHoldings = async (next: PortfolioHolding[]) => {
    setHoldings(next);
    if (sessionId) await savePortfolio(sessionId, next);
  };

  return (
    <main className="grid h-screen grid-cols-[20rem_minmax(0,1fr)] gap-4 p-4">
      <aside className="flex flex-col gap-3 overflow-y-auto">
        <h1 className="font-mono text-sm uppercase tracking-[0.18em] text-muted-foreground">
          投资操作顾问
        </h1>
        <RunPicker value={runId} onChange={setRunId} />
        <div className="rounded-lg border border-border bg-card px-3 py-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
              当前持仓
            </span>
            {sessionId && (
              <PortfolioUpload sessionId={sessionId} onExtracted={persistHoldings} />
            )}
          </div>
          <HoldingsTable holdings={holdings} onChange={persistHoldings} />
        </div>
      </aside>

      <section className="flex h-full flex-col rounded-lg border border-border bg-background">
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {messages.map((m) => (
            <ChatMessage key={m.message_id} message={m} />
          ))}
        </div>
        <div className="flex items-center gap-2 border-t border-border p-3">
          <input
            className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm"
            placeholder="问问该如何操作…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            disabled={streaming}
          />
          <Button onClick={send} disabled={streaming || !input.trim()}>
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </section>
    </main>
  );
}
```

- [ ] **Step 2: Type-check and build**

Run: `cd webui && npx tsc --noEmit && npm run build`
Expected: type-check clean; build succeeds and lists `/chat` as a route.

- [ ] **Step 3: Manual smoke (optional but recommended)**

Run backend `uvicorn api.main:app --reload --port 8000` + `cd webui && npm run dev`. Visit `http://localhost:3000/chat`. Verify: session created, run picker lists completed runs, screenshot upload populates the holdings table, sending a message streams a reply with a disclaimer.

- [ ] **Step 4: Commit**

```bash
git add webui/app/chat/page.tsx
git commit -m "feat(advisor): add chat page"
```

---

## Task 13: Docs + smoke test registration

**Files:**
- Modify: `api/README.md`
- Modify: `tests/webui/test_smoke.py`

- [ ] **Step 1: Add chat endpoints to `api/README.md`**

Under the `## Endpoints` list, append:

```markdown
- `POST   /api/chat/sessions` — create a chat session (optional `run_id`)
- `GET    /api/chat/sessions` — list chat sessions
- `GET    /api/chat/sessions/{id}` — session detail + messages
- `DELETE /api/chat/sessions/{id}` — delete a chat session
- `POST   /api/chat/sessions/{id}/portfolio` — extract holdings from a screenshot
- `PUT    /api/chat/sessions/{id}/portfolio` — overwrite holdings (manual)
- `GET    /api/chat/sessions/{id}/portfolio` — read current holdings
- `POST   /api/chat/sessions/{id}/stream` — SSE chat (token / tool_call / done / error)
```

- [ ] **Step 2: Add a smoke assertion for chat route registration**

Open `tests/webui/test_smoke.py`, find the route-registration test, and add an assertion that `/api/chat/sessions` is a registered path. Match the existing assertion style in that file (read it first). Example shape:

```python
def test_chat_routes_registered(client):
    # OPTIONS or a 404-vs-405 probe — match the file's existing convention.
    resp = client.post("/api/chat/sessions", json={})
    assert resp.status_code in (200, 422)  # registered (not 404)
```

> Read `tests/webui/test_smoke.py` first and follow its actual pattern; the snippet above is illustrative.

- [ ] **Step 3: Run full unit suite + lint**

Run: `pytest -m unit -q && ruff check .`
Expected: all pass; ruff clean.

- [ ] **Step 4: Commit**

```bash
git add api/README.md tests/webui/test_smoke.py
git commit -m "docs(advisor): document chat endpoints and smoke-test route registration"
```

---

## Self-Review

**1. Spec coverage:**
- 消费已有报告 → Task 4 (`context.py`) + Task 9 (stream route reads `run.result`). ✓
- Vision 提取持仓 → Task 6 (`vision.py`) + Task 9 (`POST .../portfolio`). ✓
- 复用 dataflows 作工具 → Task 3 (`tools.py` imports from `agent_utils`) + Task 7 (engine loop). ✓
- 新 Next.js 页面 + chat 路由 → Tasks 9–12. ✓
- 具体建议+研究框架+免责 → Task 5 (`prompt.py`). ✓
- 持久化会话+持仓 → Task 2 (3 tables + CRUD) + Task 9 (message persistence). ✓
- 方案 A 手写工具循环 → Task 7 engine. ✓
- 对话不受 409 锁 → Task 9 `test_chat_does_not_trigger_409_when_analysis_running`. ✓
- NO_DATA 诚实处理 → Task 3 `is_no_data` + Task 5 prompt rule + Task 7 marks `unavailable`. ✓
- 无视觉模型校验 → **GAP**: spec §6b 提到"所选 provider 不支持视觉时返回明确错误"。当前计划用同一 model 做视觉(real_chat_llm_factory 假设配置的是支持视觉的家族)。这是一个边界,记录如下。

**Resolution for the gap:** 计划当前依赖配置的 provider/model 为支持视觉的家族(anthropic/google/openai)。显式的"provider 不支持视觉则报错"校验留作可选增强——因为 `real_chat_llm_factory` 不知道哪些 model id 支持视觉(`model_catalog` 无 vision 标志,spec §2 已记录)。这不阻塞 MVP:若配置了非视觉模型,vision 调用会从 provider 收到错误,`extract_holdings` 解析失败返回空 `holdings[]`,前端提示手动录入——降级行为安全且符合 spec §6b 的"提取失败 → 提示手动录入"。不新增任务。

**2. Placeholder scan:** 无 TBD/TODO。所有 code steps 含完整代码。前端任务含"verify actual export names"提示(因 webui/lib 的确切导出名需实现时 grep 确认),非占位符而是必要的集成校验。

**3. Type consistency:**
- `PortfolioHolding` 字段在 schemas(Task 1)、store(Task 2)、vision(Task 6)、route(Task 9)、TS types(Task 10)间一致。✓
- `run_chat(chain, history_messages, user_message, tools_by_name)` 签名在 engine(Task 7)与 route(Task 9)调用处一致。✓
- 事件名 `tool_call`/`token`/`done`/`error` 在 engine、route、TS `ChatSSEEvent` 间一致。✓
- store 方法名 `create_chat_session`/`get_chat_session`/`list_chat_sessions`/`delete_chat_session`/`insert_chat_message`/`list_chat_messages`/`save_portfolio`/`get_portfolio` 在 Task 2 定义、Task 9 调用一致。✓

---

## 执行注意事项

- 后端任务(1–9)无网络无真实 key,`pytest -m unit` 即可全绿(`conftest.py` 注入 placeholder key)。
- 前端任务(10–12)写代码前先读 `webui/node_modules/next/dist/docs/`(Next.js 16 破坏性变更),并 grep `webui/lib/api.ts`/`types.ts` 确认 history 相关的真实导出名(如 `getHistory`/`HistorySummary`)。
- Task 8 的 main.py 改动不单独提交,与 Task 9 一起提交(避免中间态 import 失败)。
