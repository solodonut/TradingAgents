# Chat Report Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users ask the Chat LLM to clarify a report scope with clickable choices, then automatically save only the session's final confirmed conclusions and action items to a collision-safe Markdown file under `report/`.

**Architecture:** Add a focused advisor export module that owns the summarization prompt, dynamic session tools, filename sanitation, and exclusive file creation. Build those tools per Chat request so they can load only the active session from the server-side store, persist scope choices through existing tool-call metadata, and reuse the existing SSE loop. Keep the frontend thin: the title-bar shortcut sends a normal Chat message, while assistant bubbles parse structured scope-tool calls into buttons.

**Tech Stack:** Python 3.10+, LangChain messages/tools, FastAPI, SQLite, pytest, Next.js 16, React 19, TypeScript, Tailwind CSS 4, lucide-react

---

## File Map

- Create `tradingagents/advisor/export.py`: report summarization, scope/export tools, filename sanitation, and exclusive persistence.
- Create `tests/advisor/test_export.py`: export prompt, validation, collision, concurrency, and tool tests.
- Modify `tradingagents/advisor/prompt.py`: teach the Chat LLM when to clarify scope and when to export.
- Modify `tests/advisor/test_prompt.py`: lock the export-intent rules into the advisor system prompt.
- Modify `api/routes/chat.py`: construct request-scoped export tools and supply server-owned session context.
- Modify `tests/webui/test_routes_chat.py`: cover persisted choices, direct export, and session isolation.
- Create `webui/lib/chat-export.ts`: parse export tool metadata and define the shortcut prompt.
- Modify `webui/components/chat/ChatMessage.tsx`: render scope buttons and hide internal tools from data-source labels.
- Modify `webui/app/chat/page.tsx`: reuse one message-send path for typed text, shortcut export, and choice clicks.
- Modify `api/README.md`: document Chat's tool-driven report export behavior.
- Modify `CHANGELOG.md`: record the user-facing feature under Unreleased.

### Task 1: Build the Report Generator and Collision-Safe Writer

**Files:**
- Create: `tradingagents/advisor/export.py`
- Create: `tests/advisor/test_export.py`

- [ ] **Step 1: Write failing tests for summarization and file creation**

Create `tests/advisor/test_export.py` with the first core tests:

```python
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from tradingagents.advisor.export import (
    NoConfirmedContentError,
    generate_report_markdown,
    save_report,
)


class _FakeLLM:
    def __init__(self, content: str):
        self.content = content
        self.invocations = []

    def invoke(self, prompt):
        self.invocations.append(prompt)
        return AIMessage(content=self.content)


def test_generate_report_markdown_uses_scope_and_full_history():
    llm = _FakeLLM("# 最终方案\n\n- 分两次减仓。")
    history = [
        HumanMessage(content="全部清仓"),
        AIMessage(content="这个理解有误。"),
        HumanMessage(content="确认改为分两次减仓"),
    ]

    result = generate_report_markdown(llm, history, "仅导出最终仓位调整方案")

    assert result == "# 最终方案\n\n- 分两次减仓。"
    rendered = llm.invocations[0].to_string()
    assert "仅导出最终仓位调整方案" in rendered
    assert "全部清仓" in rendered
    assert "确认改为分两次减仓" in rendered
    assert "较新的明确确认覆盖较早" in rendered
    assert "排除误解" in rendered


@pytest.mark.parametrize("content", ["", "   ", "NO_CONFIRMED_CONTENT"])
def test_generate_report_markdown_rejects_missing_confirmed_content(content):
    with pytest.raises(NoConfirmedContentError):
        generate_report_markdown(_FakeLLM(content), [], "仅导出风险结论")


def test_save_report_sanitizes_title_and_increments_collisions(tmp_path):
    report_dir = tmp_path / "report"
    today = date(2026, 6, 22)

    first = save_report("# 一", '  腾讯/控股:*?  ', report_dir, today=today)
    second = save_report("# 二", '  腾讯/控股:*?  ', report_dir, today=today)

    assert first.name == "2026-06-22-腾讯控股.md"
    assert second.name == "2026-06-22-腾讯控股-2.md"
    assert first.read_text(encoding="utf-8") == "# 一\n"
    assert second.read_text(encoding="utf-8") == "# 二\n"


def test_save_report_uses_fallback_for_empty_title(tmp_path):
    path = save_report("# 结论", "<>:*?", tmp_path, today=date(2026, 6, 22))
    assert path.name == "2026-06-22-chat-report.md"


def test_save_report_is_exclusive_under_concurrency(tmp_path):
    def write(index: int):
        return save_report(
            f"# 报告 {index}",
            "并发会话",
            tmp_path,
            today=date(2026, 6, 22),
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(write, range(4)))

    assert len({path.name for path in paths}) == 4
    assert len(list(tmp_path.glob("*.md"))) == 4
```

- [ ] **Step 2: Run the new test module and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/advisor/test_export.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'tradingagents.advisor.export'`.

- [ ] **Step 3: Implement the minimal export core**

Create `tradingagents/advisor/export.py` with the complete core implementation:

```python
"""Generate and persist final-conclusion Markdown reports from Chat sessions."""

import re
from datetime import date
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

_NO_CONTENT = "NO_CONFIRMED_CONTENT"
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_EXPORT_PROMPT = """你负责把投资顾问聊天整理成 Markdown 报告。

强约束：
1. 只输出用户最终确认的结论与行动项。
2. 较新的明确确认覆盖较早的冲突内容。
3. 排除误解、被否定内容、已废弃方案、试探性建议和修正过程。
4. 严格遵守用户确认的导出范围，不加入范围外主题。
5. 不补充聊天中没有依据的事实、数字或建议。
6. 不写入导出指令、选项澄清过程或工具状态。
7. 输出完整 Markdown，并至少包含一个标题。
8. 如果范围内没有最终确认的内容，只输出 NO_CONFIRMED_CONTENT。
"""


class NoConfirmedContentError(ValueError):
    """Raised when a session has no confirmed content in the requested scope."""


def _response_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def generate_report_markdown(llm, messages: list, scope: str) -> str:
    """Summarize confirmed session content inside the caller-approved scope."""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _EXPORT_PROMPT),
            MessagesPlaceholder(variable_name="messages"),
            ("human", "已确认的导出范围：{scope}"),
        ]
    )
    rendered = prompt.invoke({"messages": messages, "scope": scope.strip()})
    result = llm.invoke(rendered)
    markdown = _response_text(result.content).strip()
    if not markdown or markdown == _NO_CONTENT:
        raise NoConfirmedContentError("所选范围内没有已确认的内容")
    return markdown


def _safe_title(title: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    cleaned = cleaned[:80].rstrip()
    return cleaned or "chat-report"


def save_report(
    markdown: str,
    session_title: str,
    report_dir: Path,
    *,
    today: date | None = None,
) -> Path:
    """Exclusively create a dated report without overwriting an existing file."""
    content = markdown.strip()
    if not content:
        raise NoConfirmedContentError("报告内容为空")

    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{(today or date.today()).isoformat()}-{_safe_title(session_title)}"
    suffix = 1
    while True:
        filename = f"{prefix}.md" if suffix == 1 else f"{prefix}-{suffix}.md"
        candidate = report_dir / filename
        created = False
        try:
            with candidate.open("x", encoding="utf-8") as handle:
                created = True
                handle.write(f"{content}\n")
            return candidate
        except FileExistsError:
            suffix += 1
        except Exception:
            if created:
                candidate.unlink(missing_ok=True)
            raise
```

- [ ] **Step 4: Run the export tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/advisor/test_export.py -q
```

Expected: `7 passed`.

- [ ] **Step 5: Commit the export core**

```bash
git add tradingagents/advisor/export.py tests/advisor/test_export.py
git commit -m "feat(chat): add report export core"
```

### Task 2: Add Validated Session-Level Export Tools and Prompt Rules

**Files:**
- Modify: `tradingagents/advisor/export.py`
- Modify: `tradingagents/advisor/prompt.py`
- Modify: `tests/advisor/test_export.py`
- Modify: `tests/advisor/test_prompt.py`

- [ ] **Step 1: Add failing tests for scope choices and export-tool output**

Add `import json` beside the existing top-level imports. Extend the existing
`from tradingagents.advisor.export import (...)` block with `ExportContext` and
`create_export_tools`, then append these tests:

```python
def _tools_by_name(tools):
    return {tool.name: tool for tool in tools}


def test_request_export_scope_requires_two_to_four_unique_options(tmp_path):
    context = ExportContext(title="测试", messages=[])
    tools = _tools_by_name(
        create_export_tools(
            llm=_FakeLLM("# 报告"),
            load_context=lambda: context,
            report_dir=tmp_path,
        )
    )

    with pytest.raises(ValueError, match="2 到 4"):
        tools["request_export_scope"].invoke(
            {"question": "导出什么？", "options": ["全部"]}
        )
    with pytest.raises(ValueError, match="互不重复"):
        tools["request_export_scope"].invoke(
            {"question": "导出什么？", "options": ["全部", "全部"]}
        )


def test_export_chat_report_rejects_positional_scope_answers(tmp_path):
    tools = _tools_by_name(
        create_export_tools(
            llm=_FakeLLM("# 报告"),
            load_context=lambda: ExportContext(title="测试", messages=[]),
            report_dir=tmp_path,
        )
    )

    with pytest.raises(ValueError, match="完整描述"):
        tools["export_chat_report"].invoke({"scope": "A"})


def test_request_export_scope_returns_the_exact_question_and_options(tmp_path):
    tools = _tools_by_name(
        create_export_tools(
            llm=_FakeLLM("# 报告"),
            load_context=lambda: ExportContext(title="测试", messages=[]),
            report_dir=tmp_path,
        )
    )

    output = tools["request_export_scope"].invoke(
        {
            "question": "请选择导出范围",
            "options": ["全部最终结论", "仅风险控制"],
        }
    )

    assert "请选择导出范围" in output
    assert "全部最终结论" in output
    assert "仅风险控制" in output


def test_export_chat_report_loads_context_and_returns_real_relative_path(tmp_path):
    llm = _FakeLLM("# 风险控制\n\n- 保留止损线。")
    context = ExportContext(
        title="风险/复盘",
        messages=[HumanMessage(content="最终采用 8% 止损线")],
    )
    tools = _tools_by_name(
        create_export_tools(
            llm=llm,
            load_context=lambda: context,
            report_dir=tmp_path / "report",
        )
    )

    output = json.loads(
        tools["export_chat_report"].invoke({"scope": "仅导出最终风险控制方案"})
    )

    assert output["status"] == "saved"
    assert output["path"].startswith("report/")
    assert (tmp_path / output["path"]).read_text(encoding="utf-8").startswith(
        "# 风险控制"
    )
    assert "最终采用 8% 止损线" in llm.invocations[0].to_string()
```

Append this behavior assertion to `tests/advisor/test_prompt.py` (its existing
`build_system_prompt` import already covers the test):

```python
def test_prompt_defines_contextual_export_behavior():
    prompt = build_system_prompt("报告", "持仓")
    assert "明确表达导出" in prompt
    assert "request_export_scope" in prompt
    assert "2 到 4 个" in prompt
    assert "export_chat_report" in prompt
    assert "总结一下" in prompt
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/advisor/test_export.py tests/advisor/test_prompt.py -q
```

Expected: FAIL because `ExportContext`, `create_export_tools`, and the export prompt rules do not exist.

- [ ] **Step 3: Add the request-scoped tool factory**

Add these imports and definitions to `tradingagents/advisor/export.py`:

```python
import json
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.tools import tool


@dataclass(frozen=True)
class ExportContext:
    title: str
    messages: list


def create_export_tools(
    *,
    llm,
    load_context: Callable[[], ExportContext],
    report_dir: Path,
) -> list:
    """Create tools bound to one Chat session through a server-owned loader."""

    @tool
    def request_export_scope(question: str, options: list[str]) -> str:
        """Ask the user to choose an export scope when their intent is ambiguous."""
        clean_question = question.strip()
        clean_options = [option.strip() for option in options if option.strip()]
        if not clean_question:
            raise ValueError("导出范围问题不能为空")
        if not 2 <= len(clean_options) <= 4:
            raise ValueError("导出范围必须提供 2 到 4 个选项")
        if len(clean_options) != len(set(clean_options)):
            raise ValueError("导出范围选项必须互不重复")
        lines = "\n".join(f"- {option}" for option in clean_options)
        return f"等待用户选择，当前不要导出。\n{clean_question}\n{lines}"

    @tool
    def export_chat_report(scope: str) -> str:
        """Generate and save a report after the export scope is fully confirmed."""
        clean_scope = scope.strip()
        if not clean_scope:
            raise ValueError("导出范围不能为空")
        positional_answers = {"A", "B", "C", "D", "第一个选项", "第二个选项"}
        if clean_scope.upper() in positional_answers:
            raise ValueError("导出范围必须是自洽的完整描述")
        context = load_context()
        markdown = generate_report_markdown(llm, context.messages, clean_scope)
        path = save_report(markdown, context.title, report_dir)
        return json.dumps(
            {"status": "saved", "path": f"report/{path.name}"},
            ensure_ascii=False,
        )

    return [request_export_scope, export_chat_report]
```

- [ ] **Step 4: Add export-decision rules to the advisor prompt**

Insert this section into `_TEMPLATE` in `tradingagents/advisor/prompt.py`, before `# 可用实时数据工具`:

```python
# 会话报告导出
仅当用户明确表达导出、保存成文档或生成 Markdown 等落盘意图时,才进入导出流程。普通的“总结一下”只需在聊天中回答,不得创建文件。
- 如果导出范围存在多种合理解释,调用 request_export_scope。根据当前会话主题提供 2 到 4 个明确、互斥的选项,并在回复正文中完整复述问题和选项。用户选择后仍不明确时继续调用该工具,不得猜测。
- 如果范围已经完整、具体,调用 export_chat_report。scope 必须是自洽的完整描述,不能只写“A”或“第一个选项”。
- 标题栏快捷指令会明确要求“先提供可选范围”,收到该指令时必须调用 request_export_scope,不得直接导出。
- 只有 export_chat_report 返回 status=saved 后才能声称成功,并原样引用工具返回的 path。
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/advisor/test_export.py tests/advisor/test_prompt.py -q
```

Expected: all focused tests pass.

- [ ] **Step 6: Commit the tools and prompt behavior**

```bash
git add tradingagents/advisor/export.py tradingagents/advisor/prompt.py tests/advisor/test_export.py tests/advisor/test_prompt.py
git commit -m "feat(chat): add contextual export tools"
```

### Task 3: Wire Export Tools into the Chat Route

**Files:**
- Modify: `api/routes/chat.py`
- Modify: `tests/webui/test_routes_chat.py`

- [ ] **Step 1: Write failing route tests for choices and direct export**

Append these tests to `tests/webui/test_routes_chat.py`:

```python
def test_stream_chat_persists_export_scope_choices(client, monkeypatch, tmp_path):
    import api.routes.chat as chat_routes

    monkeypatch.setattr(chat_routes, "REPORT_DIR", tmp_path / "report")
    scope_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "request_export_scope",
                "args": {
                    "question": "请选择导出范围",
                    "options": ["全部最终结论", "仅风险控制"],
                },
                "id": "scope-1",
            }
        ],
    )
    final = AIMessage(content="请选择导出范围：全部最终结论，或仅风险控制。")
    _install_fake_chat(client, [scope_call, final])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]

    with client.stream(
        "POST",
        f"/api/chat/sessions/{sid}/stream",
        json={"message": "请导出当前会话，先给我范围选项"},
    ) as stream:
        body = "".join(stream.iter_text())

    assert "request_export_scope" in body
    messages = client.get(f"/api/chat/sessions/{sid}").json()["messages"]
    call = messages[-1]["tool_calls"][0]
    assert call["tool"] == "request_export_scope"
    assert call["args"]["options"] == ["全部最终结论", "仅风险控制"]
    assert not (tmp_path / "report").exists()


def test_stream_chat_exports_only_the_active_session(client, monkeypatch, tmp_path):
    import api.main as main
    import api.routes.chat as chat_routes

    monkeypatch.setattr(chat_routes, "REPORT_DIR", tmp_path / "report")
    store = main.get_store()
    first = client.post("/api/chat/sessions", json={}).json()["session_id"]
    second = client.post("/api/chat/sessions", json={}).json()["session_id"]
    store.rename_chat_session(first, "第一会话")
    store.rename_chat_session(second, "第二会话")
    store.insert_chat_message("m1", first, "user", "最终采用分批减仓", [])
    store.insert_chat_message("m2", second, "user", "另一会话的秘密内容", [])
    captured = {}

    def fake_generate_report_markdown(llm, messages, scope):
        captured["messages"] = [message.content for message in messages]
        captured["scope"] = scope
        return "# 最终方案\n\n- 分批减仓。"

    monkeypatch.setattr(
        "tradingagents.advisor.export.generate_report_markdown",
        fake_generate_report_markdown,
    )

    export_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "export_chat_report",
                "args": {"scope": "仅导出最终仓位调整方案"},
                "id": "export-1",
            }
        ],
    )
    final = AIMessage(content="报告已生成。")
    _install_fake_chat(
        client,
        [export_call, final],
    )

    with client.stream(
        "POST",
        f"/api/chat/sessions/{first}/stream",
        json={"message": "导出最终仓位调整方案"},
    ) as stream:
        "".join(stream.iter_text())

    files = list((tmp_path / "report").glob("*.md"))
    assert len(files) == 1
    assert "第一会话" in files[0].name
    assert "最终采用分批减仓" in captured["messages"]
    assert "另一会话的秘密内容" not in captured["messages"]
    assert captured["scope"] == "仅导出最终仓位调整方案"
    messages = client.get(f"/api/chat/sessions/{first}").json()["messages"]
    assert messages[-1]["tool_calls"][0]["tool"] == "export_chat_report"
```

- [ ] **Step 2: Run the route tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/webui/test_routes_chat.py -q
```

Expected: FAIL because the bound tool list does not include either export tool and `REPORT_DIR` does not exist.

- [ ] **Step 3: Add server-owned history conversion and request-scoped tools**

Update imports and constants in `api/routes/chat.py`:

```python
from pathlib import Path

from tradingagents.advisor.export import ExportContext, create_export_tools

REPORT_DIR = Path(__file__).resolve().parents[2] / "report"
```

Add a single history helper above the routes:

```python
def _chat_history(store, session_id: str) -> list:
    history = []
    for message in store.list_chat_messages(session_id):
        if message.role == "user":
            history.append(HumanMessage(content=message.content))
        else:
            history.append(AIMessage(content=message.content))
    return history
```

In `stream_chat`, replace the hand-built history loop with:

```python
history = _chat_history(store, session_id)
```

After obtaining `chat_llm`, construct the session loader and combined tool list:

```python
def load_export_context() -> ExportContext:
    current_session = store.get_chat_session(session_id)
    if current_session is None:
        raise ValueError("session not found")
    return ExportContext(
        title=current_session.title or "chat-report",
        messages=_chat_history(store, session_id),
    )


export_tools = create_export_tools(
    llm=chat_llm,
    load_context=load_export_context,
    report_dir=REPORT_DIR,
)
chat_tools = [*ADVISOR_TOOLS, *export_tools]
```

Bind and index `chat_tools` instead of the global list:

```python
bound = chat_llm.bind_tools(chat_tools)
tools_by_name = {tool.name: tool for tool in chat_tools}
```

Keep `store.insert_chat_message(...)` before starting the worker. This guarantees that `load_export_context()` sees the current export request or clicked option in addition to all prior persisted messages.

- [ ] **Step 4: Run route and advisor tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/webui/test_routes_chat.py tests/advisor -q
```

Expected: all route and advisor tests pass.

- [ ] **Step 5: Commit backend integration**

```bash
git add api/routes/chat.py tests/webui/test_routes_chat.py
git commit -m "feat(api): wire chat report export"
```

### Task 4: Render Persisted Export Scope Choices

**Files:**
- Create: `webui/lib/chat-export.ts`
- Modify: `webui/components/chat/ChatMessage.tsx`

- [ ] **Step 1: Add a focused metadata parser**

Create `webui/lib/chat-export.ts`:

```typescript
import type { ChatMessageT } from "@/lib/types";

export const EXPORT_REPORT_PROMPT =
  "请根据当前会话导出报告。请先根据上下文提供可选的导出范围，不要立即导出。";

export const INTERNAL_EXPORT_TOOLS = new Set([
  "request_export_scope",
  "export_chat_report",
]);

export function exportScopeOptions(message: ChatMessageT): string[] {
  const call = message.tool_calls.find(
    (item) => item.tool === "request_export_scope",
  );
  const args = call?.args;
  if (!args || typeof args !== "object") return [];
  const options = (args as { options?: unknown }).options;
  if (!Array.isArray(options)) return [];
  return options.filter(
    (option): option is string => typeof option === "string" && option.trim().length > 0,
  );
}

export function visibleDataSources(message: ChatMessageT): string[] {
  return message.tool_calls
    .map((item) => (typeof item.tool === "string" ? item.tool : ""))
    .filter((name) => name && !INTERNAL_EXPORT_TOOLS.has(name));
}
```

- [ ] **Step 2: Render choice buttons and filter internal tools**

Replace `webui/components/chat/ChatMessage.tsx` with:

```tsx
"use client";

import { LoaderCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { exportScopeOptions, visibleDataSources } from "@/lib/chat-export";
import { MarkdownContent } from "@/components/MarkdownContent";
import type { ChatMessageT } from "@/lib/types";

export function ChatMessage({
  message,
  choicesEnabled = false,
  onChoice,
}: {
  message: ChatMessageT;
  choicesEnabled?: boolean;
  onChoice?: (choice: string) => void;
}) {
  const isUser = message.role === "user";
  const isThinking = message.role === "assistant" && message.content.trim().length === 0;
  const choices = exportScopeOptions(message);
  const dataSources = visibleDataSources(message);

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[80%] rounded-lg px-3 py-2",
          isThinking
            ? "thinking-border min-w-40"
            : isUser
              ? "glass border-primary/30 bg-primary/10"
              : "glass-readable",
        )}
        aria-busy={isThinking ? "true" : undefined}
      >
        {isThinking ? (
          <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em]">
            <LoaderCircle className="size-3.5 animate-spin motion-reduce:animate-none" />
            正在思考
          </div>
        ) : isUser ? (
          <p className="whitespace-pre-wrap text-sm">{message.content}</p>
        ) : (
          <MarkdownContent content={message.content} />
        )}

        {choices.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2" aria-label="导出范围选项">
            {choices.map((choice) => (
              <button
                key={choice}
                type="button"
                disabled={!choicesEnabled}
                onClick={() => onChoice?.(choice)}
                className="glass-control rounded-md px-2.5 py-1.5 text-left text-xs text-foreground transition-colors hover:border-primary/60 hover:text-primary disabled:cursor-not-allowed disabled:opacity-45"
              >
                {choice}
              </button>
            ))}
          </div>
        )}

        {dataSources.length > 0 && (
          <div className="mt-1 font-mono text-[0.6rem] text-muted-foreground">
            数据来源: {dataSources.join(", ")}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Run frontend lint and verify the isolated components compile**

Run:

```bash
cd webui && npm run lint
```

Expected: ESLint exits 0 with no errors.

- [ ] **Step 4: Commit the choice UI**

```bash
git add webui/lib/chat-export.ts webui/components/chat/ChatMessage.tsx
git commit -m "feat(webui): render chat export choices"
```

### Task 5: Add the Title-Bar Shortcut and Reuse the Chat Send Path

**Files:**
- Modify: `webui/app/chat/page.tsx`

- [ ] **Step 1: Refactor sending around an explicit message argument**

Import the export icon and helper:

```tsx
import {
  Calculator,
  Check,
  FileDown,
  Home,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Plus,
  Send,
  Trash2,
  X,
} from "lucide-react";
import { EXPORT_REPORT_PROMPT, exportScopeOptions } from "@/lib/chat-export";
```

Replace the current `send` function with a reusable function plus a thin input handler:

```tsx
const sendMessage = async (rawQuestion: string) => {
  const question = rawQuestion.trim();
  if (!sessionId || !question || streaming) return;
  const now = Date.now();
  const userMsg: ChatMessageT = {
    message_id: `local-${now}`,
    session_id: sessionId,
    role: "user",
    content: question,
    tool_calls: [],
    created_at: new Date().toISOString(),
  };
  setMessages((current) => [...current, userMsg]);
  setInput("");
  setStreaming(true);
  streamingRef.current = "";

  const assistantId = `stream-${now}`;
  setMessages((current) => [
    ...current,
    {
      message_id: assistantId,
      session_id: sessionId,
      role: "assistant",
      content: "",
      tool_calls: [],
      created_at: new Date().toISOString(),
    },
  ]);

  try {
    await streamChat(chatStreamUrl(sessionId), question, (event) => {
      if (event.event === "token") {
        streamingRef.current += event.data.content;
        setMessages((current) =>
          current.map((message) =>
            message.message_id === assistantId
              ? { ...message, content: streamingRef.current }
              : message,
          ),
        );
      } else if (event.event === "done") {
        setMessages((current) =>
          current.map((message) =>
            message.message_id === assistantId
              ? {
                  ...message,
                  content: event.data.content,
                  tool_calls: event.data.tool_calls,
                }
              : message,
          ),
        );
      } else if (event.event === "error") {
        setMessages((current) =>
          current.map((message) =>
            message.message_id === assistantId
              ? { ...message, content: `⚠️ 出错了:${event.data.message}` }
              : message,
          ),
        );
      }
    });
  } finally {
    setStreaming(false);
    void refreshSessions();
  }
};

const send = () => void sendMessage(input);
```

This preserves the existing typed-message behavior while allowing the shortcut and choice buttons to send exact messages without mutating the input first.

- [ ] **Step 2: Compute the active choice message and export availability**

Place these derived values after `currentTitle`:

```tsx
const latestMessage = messages.at(-1);
const activeChoiceMessageId =
  latestMessage?.role === "assistant" && exportScopeOptions(latestMessage).length > 0
    ? latestMessage.message_id
    : null;
const canRequestExport =
  Boolean(sessionId) &&
  !streaming &&
  !deletingSessionId &&
  messages.some(
    (message) => message.role === "assistant" && message.content.trim().length > 0,
  );
```

- [ ] **Step 3: Add the title-bar export shortcut**

In the title-bar action container, before the workbench link, add:

```tsx
<Button
  type="button"
  variant="outline"
  size="sm"
  onClick={() => void sendMessage(EXPORT_REPORT_PROMPT)}
  disabled={!canRequestExport}
  aria-label="导出当前会话报告"
  title="通过对话选择范围并导出报告"
>
  <FileDown className="size-3.5" aria-hidden="true" />
  导出报告
</Button>
```

- [ ] **Step 4: Connect scope buttons to the same send path**

Replace the message map with:

```tsx
{messages.map((message) => (
  <ChatMessage
    key={message.message_id}
    message={message}
    choicesEnabled={message.message_id === activeChoiceMessageId && !streaming}
    onChoice={(choice) => void sendMessage(choice)}
  />
))}
```

Keep the input keyboard handler as `onKeyDown={(event) => event.key === "Enter" && send()}` and the existing send button as `onClick={send}`.

- [ ] **Step 5: Run Next.js checks**

The page is already a Client Component, matching `webui/node_modules/next/dist/docs/01-app/01-getting-started/05-server-and-client-components.md`; no Server Action or new route is needed.

Run:

```bash
cd webui && npm run lint && npm run build
```

Expected: ESLint exits 0 and Next.js 16 reports a successful production build.

- [ ] **Step 6: Commit the shortcut flow**

```bash
git add webui/app/chat/page.tsx
git commit -m "feat(webui): add chat report shortcut"
```

### Task 6: Document and Verify the Complete Feature

**Files:**
- Modify: `api/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Document the behavior without inventing a new endpoint**

Add this paragraph after the Chat endpoint list in `api/README.md`:

```markdown
Chat report export is tool-driven through the existing session stream endpoint.
Explicit export requests either produce persisted clickable scope choices or,
once the scope is clear, save a collision-safe Markdown report under the project
`report/` directory. The title-bar shortcut sends a normal Chat message and does
not use a separate export endpoint.
```

- [ ] **Step 2: Record the feature in the changelog**

Add this bullet under `## [Unreleased]` → `### Added` in `CHANGELOG.md`:

```markdown
- **Context-aware Chat report export.** The advisor can clarify an ambiguous
  export scope with persisted clickable choices, then save only the session's
  final confirmed conclusions and action items as a dated, collision-safe
  Markdown file under `report/`.
```

- [ ] **Step 3: Run the full non-integration backend suite**

Run:

```bash
.venv/bin/python -m pytest -m "not integration"
```

Expected: all selected tests pass; the DeepSeek integration test is excluded.

- [ ] **Step 4: Run whole-repository lint**

Run:

```bash
.venv/bin/ruff check .
```

Expected: Ruff exits 0.

- [ ] **Step 5: Run final frontend verification**

Run:

```bash
cd webui && npm run lint && npm run build
```

Expected: ESLint exits 0 and the Next.js production build succeeds.

- [ ] **Step 6: Inspect the final diff for scope and generated artifacts**

Run:

```bash
git status --short
git diff --check
git diff --stat ad39bbd..HEAD
```

Expected: no whitespace errors; only files listed in this plan are feature changes. Do not stage or modify the pre-existing changes in `tests/test_openai_compatible_provider.py` or `tradingagents/llm_clients/openai_client.py`, and do not commit `.superpowers/` visual-companion artifacts.

- [ ] **Step 7: Commit documentation**

```bash
git add api/README.md CHANGELOG.md
git commit -m "docs(chat): document report export"
```
