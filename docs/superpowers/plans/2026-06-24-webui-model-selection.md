# Web 页面模型选择 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在 Web 页面（分析工作台 + Chat）于当前已配置 provider 内自行选择 LLM 模型。

**Architecture:** 后端把 `model_catalog.get_model_options(provider, mode)` 的结果通过现有 `GET /api/config/options` 暴露给前端；Chat 增加可选 `chat_llm` 请求字段并透传给 LLM 工厂。前端在分析页加 deep/quick 两个下拉、Chat 页加一个合并下拉，默认值来自后端配置，选择记忆在浏览器 `localStorage`。分析功能后端已打通（`real_graph_factory` 已覆盖 config），无需改后端。

**Tech Stack:** FastAPI + Pydantic v2（后端）、pytest（后端测试）、Next.js 16 + React 19 + TypeScript（前端，无测试框架，手动验证）。

## Global Constraints

- Python 命令一律用 `.venv/bin/python`（系统 python 可能 < 3.10 且 NumPy 版本冲突）。
- 后端 Pydantic 联合类型用 `X | None` 语法（Python ≥ 3.10）。
- 范围限定：**只在当前 `configured_provider` 内换模型**，不做跨 provider 切换、不做 key 检测、不做 Custom 文本框降级。
- 收尾必须手动跑：`.venv/bin/python -m ruff check .` 和 `.venv/bin/python -m pytest -m "not integration"`（无 CI）。
- Commit 用 Conventional Commits（`feat(scope):` / `test(scope):`），并更新 `CHANGELOG.md`（Keep a Changelog 格式）。
- 改 `webui/` 前先看 `webui/node_modules/next/dist/docs/`（Next.js 16 有破坏性差异）。
- 回复用户一律中文。

---

## 文件结构

**后端**
- Modify: `api/schemas.py` — `ConfigOptions` 加 `model_options` 字段；`ChatRequest` 加 `chat_llm` 字段。
- Modify: `api/config_options.py` — `build_config_options()` 填充 `model_options`，新增私有 helper `_provider_model_options()`。
- Modify: `api/main.py` — `real_chat_llm_factory()` 接受可选 `model` 参数。
- Modify: `api/routes/chat.py` — `stream_chat` 把 `req.chat_llm` 透传给工厂。
- Modify: `tests/webui/test_config_options.py` — 新增 `model_options` 断言。
- Modify: `tests/webui/test_routes_chat.py` — fake factory 接受 `model` 参数；新增 chat_llm 透传断言。

**前端**
- Modify: `webui/lib/types.ts` — `ConfigOptions` 加 `model_options`。
- Modify: `webui/lib/sse.ts` — `streamChat` 加可选 `model` 参数。
- Modify: `webui/components/ConfigCard.tsx` — 加 deep/quick 两个下拉 + localStorage。
- Modify: `webui/app/chat/page.tsx` — 加模型下拉 + localStorage + 传 `chat_llm`。

---

### Task 1: 后端 — `GET /api/config/options` 暴露 `model_options`

**Files:**
- Modify: `api/schemas.py:56-62`（`ConfigOptions`）
- Modify: `api/config_options.py:1-42`
- Test: `tests/webui/test_config_options.py`

**Interfaces:**
- Consumes: `tradingagents.llm_clients.model_catalog.get_model_options(provider: str, mode: str) -> list[tuple[str, str]]`（`mode` 为 `"deep"` 或 `"quick"`；未知 provider 抛 `KeyError`）。
- Produces: `ConfigOptions.model_options: dict[str, list[tuple[str, str]]]`，形如 `{"deep": [(label, id), ...], "quick": [(label, id), ...]}`；私有 helper `_provider_model_options(provider: str | None) -> dict[str, list[tuple[str, str]]]`。

- [ ] **Step 1: 写失败测试**

在 `tests/webui/test_config_options.py` 末尾追加：

```python
def test_model_options_present_for_configured_provider():
    opts = build_config_options()
    assert set(opts.model_options.keys()) == {"deep", "quick"}
    # 默认 provider 是 ibm_ica，有具体模型列表
    assert len(opts.model_options["deep"]) > 0
    assert len(opts.model_options["quick"]) > 0
    # 每个选项是 (label, model_id) 二元组
    label, model_id = opts.model_options["deep"][0]
    assert isinstance(label, str) and isinstance(model_id, str)


def test_model_options_empty_for_unknown_provider(monkeypatch):
    import api.config_options as mod

    monkeypatch.setattr(
        mod,
        "DEFAULT_CONFIG",
        {**mod.DEFAULT_CONFIG, "llm_provider": "nonexistent_provider"},
    )
    opts = build_config_options()
    assert opts.model_options == {"deep": [], "quick": []}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_config_options.py -v`
Expected: FAIL — `ConfigOptions` 无 `model_options` 字段（`AttributeError` / validation error）。

- [ ] **Step 3: 改 schema**

`api/schemas.py`，把 `ConfigOptions` 改为：

```python
class ConfigOptions(BaseModel):
    analysts: list[dict]
    research_depth: list[dict]
    languages: list[str]
    configured_provider: str | None
    configured_deep_llm: str | None
    configured_quick_llm: str | None
    model_options: dict[str, list[tuple[str, str]]]
```

- [ ] **Step 4: 填充 model_options**

`api/config_options.py`，顶部 import 改为：

```python
from api.schemas import ConfigOptions
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.model_catalog import get_model_options
```

在 `build_config_options` 之前新增 helper：

```python
def _provider_model_options(provider: str | None) -> dict[str, list[tuple[str, str]]]:
    """当前 provider 的 deep/quick 模型选项；未知或缺失时返回空列表。"""
    if not provider:
        return {"deep": [], "quick": []}
    try:
        return {
            "deep": get_model_options(provider, "deep"),
            "quick": get_model_options(provider, "quick"),
        }
    except KeyError:
        return {"deep": [], "quick": []}
```

把 `build_config_options` 的 return 改为带上 `model_options`：

```python
def build_config_options() -> ConfigOptions:
    provider = DEFAULT_CONFIG.get("llm_provider")
    return ConfigOptions(
        analysts=_ANALYSTS,
        research_depth=_DEPTH,
        languages=_LANGUAGES,
        configured_provider=provider,
        configured_deep_llm=DEFAULT_CONFIG.get("deep_think_llm"),
        configured_quick_llm=DEFAULT_CONFIG.get("quick_think_llm"),
        model_options=_provider_model_options(provider),
    )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_config_options.py -v`
Expected: PASS（含原有用例）。

- [ ] **Step 6: 提交**

```bash
git add api/schemas.py api/config_options.py tests/webui/test_config_options.py
git commit -m "feat(api): expose provider model options in /api/config/options"
```

---

### Task 2: 后端 — Chat 透传 `chat_llm` 模型参数

**Files:**
- Modify: `api/schemas.py:95-96`（`ChatRequest`）
- Modify: `api/main.py:157-177`（`real_chat_llm_factory`）
- Modify: `api/routes/chat.py:318-340`（`stream_chat`）
- Test: `tests/webui/test_routes_chat.py`

**Interfaces:**
- Consumes: `app.state.chat_llm_factory`（可调用，现签名无参）。
- Produces: `ChatRequest.chat_llm: str | None`；`real_chat_llm_factory(model: str | None = None) -> tuple[chat_llm, vision_llm]`；`stream_chat` 调用改为 `request.app.state.chat_llm_factory(model=req.chat_llm)`。

- [ ] **Step 1: 写失败测试**

先把 `tests/webui/test_routes_chat.py` 的 `_install_fake_chat`（约 line 10-36）里的工厂改为接受 `model` 并记录，返回也带上记录器。把：

```python
    def factory():
        chain = _FakeChain(chat_responses)
        llm = _FakeLLM(chain, vision_content)
        return llm, llm

    main.app.state.chat_llm_factory = factory
```

改为：

```python
    received = {}

    def factory(model=None):
        received["model"] = model
        chain = _FakeChain(chat_responses)
        llm = _FakeLLM(chain, vision_content)
        return llm, llm

    main.app.state.chat_llm_factory = factory
    return received
```

并把函数签名 `def _install_fake_chat(client, chat_responses, vision_content="[]"):` 保持不变（返回值新增 `received`，旧调用忽略返回值不受影响）。

然后在文件末尾新增两个用例：

```python
def test_stream_chat_passes_chat_llm_to_factory(client):
    received = _install_fake_chat(client, [AIMessage(content="ok")])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    with client.stream(
        "POST",
        f"/api/chat/sessions/{sid}/stream",
        json={"message": "hi", "chat_llm": "claude-opus-4-8"},
    ) as stream:
        "".join(stream.iter_text())
    assert received["model"] == "claude-opus-4-8"


def test_stream_chat_defaults_model_to_none_when_absent(client):
    received = _install_fake_chat(client, [AIMessage(content="ok")])
    sid = client.post("/api/chat/sessions", json={}).json()["session_id"]
    with client.stream(
        "POST", f"/api/chat/sessions/{sid}/stream", json={"message": "hi"}
    ) as stream:
        "".join(stream.iter_text())
    assert received["model"] is None
```

注意：文件顶部已 `from langchain_core.messages import AIMessage`，无需新增 import。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_chat.py -k "chat_llm or defaults_model" -v`
Expected: FAIL — `stream_chat` 仍以无参方式调用工厂，且 `ChatRequest` 无 `chat_llm` 字段，`received["model"]` 不会被设置/为 None 时调用报错。

- [ ] **Step 3: schema 加字段**

`api/schemas.py`，把 `ChatRequest` 改为：

```python
class ChatRequest(BaseModel):
    message: str
    chat_llm: str | None = None
```

- [ ] **Step 4: 工厂接受 model 参数**

`api/main.py`，把 `real_chat_llm_factory` 改为：

```python
def real_chat_llm_factory(model: str | None = None):
    """Build (chat_llm, vision_llm) LangChain models from DEFAULT_CONFIG.

    Both use the configured provider. ``model`` overrides the chat model when
    provided (still on the configured provider); otherwise falls back to the
    configured quick_think_llm. The vision model must support image input
    (anthropic / google / openai families). set_config() makes the dataflows
    vendor routing match the configured data_vendors.
    """
    from tradingagents.dataflows.config import set_config
    from tradingagents.llm_clients import create_llm_client

    config = DEFAULT_CONFIG.copy()
    set_config(config)

    provider = config["llm_provider"]
    chat_model = model or config["quick_think_llm"]
    base_url = config.get("backend_url")

    client = create_llm_client(provider=provider, model=chat_model, base_url=base_url)
    chat_llm = client.get_llm()
    vision_llm = chat_llm
    return chat_llm, vision_llm
```

- [ ] **Step 5: 路由透传**

`api/routes/chat.py:340`，把：

```python
    chat_llm, _ = request.app.state.chat_llm_factory()
```

改为：

```python
    chat_llm, _ = request.app.state.chat_llm_factory(model=req.chat_llm)
```

- [ ] **Step 6: 修复另一个 no-arg fake 工厂**

`tests/webui/test_routes_chat.py` 约 line 573，`test_stream_chat_registers_profile_tools_and_injects_profile` 内：

```python
    main.app.state.chat_llm_factory = lambda: (_LLM(), _LLM())
```

改为接受可选 model：

```python
    main.app.state.chat_llm_factory = lambda model=None: (_LLM(), _LLM())
```

- [ ] **Step 7: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_chat.py -v`
Expected: PASS（新用例 + 全部原有 chat 用例）。

- [ ] **Step 8: 提交**

```bash
git add api/schemas.py api/main.py api/routes/chat.py tests/webui/test_routes_chat.py
git commit -m "feat(api): allow chat to select model via chat_llm request field"
```

---

### Task 3: 前端 — 类型与 SSE 客户端

**Files:**
- Modify: `webui/lib/types.ts:17-24`（`ConfigOptions`）
- Modify: `webui/lib/sse.ts:39-50`（`streamChat`）

**Interfaces:**
- Produces: `ConfigOptions.model_options: { deep: [string, string][]; quick: [string, string][] }`；`streamChat(url, message, onEvent, signal?, model?)` 新增第 5 个可选参数 `model?: string`，存在时请求体带 `chat_llm`。

- [ ] **Step 1: 改 ConfigOptions 类型**

`webui/lib/types.ts`，把 `ConfigOptions` 改为：

```typescript
export interface ConfigOptions {
  analysts: { value: string; label: string }[];
  research_depth: { value: number; label: string }[];
  languages: string[];
  configured_provider: string | null;
  configured_deep_llm: string | null;
  configured_quick_llm: string | null;
  model_options: { deep: [string, string][]; quick: [string, string][] };
}
```

- [ ] **Step 2: streamChat 支持 model**

`webui/lib/sse.ts`，把 `streamChat` 签名与 body 改为：

```typescript
export async function streamChat(
  url: string,
  message: string,
  onEvent: (e: ChatSSEEvent) => void,
  signal?: AbortSignal,
  model?: string,
): Promise<void> {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(model ? { message, chat_llm: model } : { message }),
    signal,
  });
```

（函数体其余部分不变。）

- [ ] **Step 3: 类型检查**

Run: `cd webui && npx tsc --noEmit`
Expected: 无新增类型错误（此时 ConfigCard/chat 尚未用新字段，但类型合法）。

- [ ] **Step 4: 提交**

```bash
git add webui/lib/types.ts webui/lib/sse.ts
git commit -m "feat(webui): add model_options type and chat_llm to streamChat"
```

---

### Task 4: 前端 — 分析页 ConfigCard 模型下拉

**Files:**
- Modify: `webui/components/ConfigCard.tsx`

**Interfaces:**
- Consumes: `ConfigOptions.model_options.{deep,quick}`、`configured_deep_llm`、`configured_quick_llm`（来自 Task 3）。
- Produces: 提交 `AnalysisRequest` 时 `deep_think_llm` / `quick_think_llm` 填用户所选值（替换写死的 `null`）。

- [ ] **Step 1: 读 Next.js 16 文档（如未读）**

确认 `"use client"` 组件中访问 `localStorage` 的注意事项（避免 SSR 期访问导致 hydration 报错）——本任务用 `useEffect` 在挂载后读取，规避该问题。Run: `ls webui/node_modules/next/dist/docs/` 并按需查阅。

- [ ] **Step 2: 加 state 与 localStorage 回填**

`webui/components/ConfigCard.tsx`，在现有 `const [language, setLanguage] = useState("Chinese");`（约 line 25）之后新增：

```tsx
  const [deepLlm, setDeepLlm] = useState(options.configured_deep_llm ?? "");
  const [quickLlm, setQuickLlm] = useState(options.configured_quick_llm ?? "");

  // 挂载后从 localStorage 回填用户上次的选择（仅当仍是当前 provider 的有效选项）
  useEffect(() => {
    const validDeep = new Set(options.model_options.deep.map(([, id]) => id));
    const validQuick = new Set(options.model_options.quick.map(([, id]) => id));
    const savedDeep = localStorage.getItem("ta:deep_think_llm");
    const savedQuick = localStorage.getItem("ta:quick_think_llm");
    if (savedDeep && validDeep.has(savedDeep)) setDeepLlm(savedDeep);
    if (savedQuick && validQuick.has(savedQuick)) setQuickLlm(savedQuick);
  }, [options]);
```

并在文件顶部把 `import { useState } from "react";` 改为 `import { useEffect, useState } from "react";`。

- [ ] **Step 3: 提交时带上所选模型**

把 `onStart({...})` 里的：

```tsx
          llm_provider: null,
          deep_think_llm: null,
          quick_think_llm: null,
```

改为：

```tsx
          llm_provider: null,
          deep_think_llm: deepLlm || null,
          quick_think_llm: quickLlm || null,
```

- [ ] **Step 4: 加两个下拉 UI**

在 `Research` 这个 `<fieldset>` 结束 `</fieldset>`（约 line 172）之后、提交按钮 `<button type="submit"`（约 line 174）之前，插入一个新的 fieldset：

```tsx
        <fieldset className="space-y-2">
          <legend className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
            Models
          </legend>
          <label className="block space-y-1">
            <span className="text-[0.7rem] text-muted-foreground">深度思考模型</span>
            <select
              value={deepLlm}
              onChange={(e) => {
                setDeepLlm(e.target.value);
                localStorage.setItem("ta:deep_think_llm", e.target.value);
              }}
              className="glass-control h-9 w-full rounded-md px-2.5 font-mono text-sm text-foreground outline-none transition-colors focus:border-primary"
            >
              {options.model_options.deep.map(([label, id]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1">
            <span className="text-[0.7rem] text-muted-foreground">快速思考模型</span>
            <select
              value={quickLlm}
              onChange={(e) => {
                setQuickLlm(e.target.value);
                localStorage.setItem("ta:quick_think_llm", e.target.value);
              }}
              className="glass-control h-9 w-full rounded-md px-2.5 font-mono text-sm text-foreground outline-none transition-colors focus:border-primary"
            >
              {options.model_options.quick.map(([label, id]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </fieldset>
```

- [ ] **Step 5: 类型检查 + 手动验证**

Run: `cd webui && npx tsc --noEmit`（无类型错误）。
手动验证（需后端在跑 `./dev.sh` 或单独起 API+web）：
1. 打开分析页，确认出现「深度思考模型」「快速思考模型」两个下拉，默认选中 `.env` 配置值。
2. 改选某个模型 → 刷新页面 → 选择被记住。
3. 开始一次分析，确认请求体里 `deep_think_llm` / `quick_think_llm` 为所选值（浏览器 Network 面板）。

- [ ] **Step 6: 提交**

```bash
git add webui/components/ConfigCard.tsx
git commit -m "feat(webui): add deep/quick model selectors to analysis config"
```

---

### Task 5: 前端 — Chat 页模型下拉

**Files:**
- Modify: `webui/app/chat/page.tsx`

**Interfaces:**
- Consumes: `ConfigOptions.model_options.{deep,quick}`、`configured_quick_llm`、`getConfigOptions()`（`webui/lib/api.ts` 已有）、`streamChat(..., model?)`（Task 3）。
- Produces: 发消息时把所选模型作为 `streamChat` 第 5 个参数传入。

- [ ] **Step 1: 读现有 chat 页结构**

Run: 用 Read 看 `webui/app/chat/page.tsx` 的 import 区、state 区（约 line 1-90）、发送逻辑（约 line 200-260）、以及输入框/页头 JSX，确定下拉放置位置与 `getConfigOptions` 是否已引入。

- [ ] **Step 2: 加配置加载与模型 state**

在 import 区确保引入 `getConfigOptions`（来自 `@/lib/api`）和 `useEffect`、`useState`（多数已存在）。在组件 state 区新增：

```tsx
  const [chatModels, setChatModels] = useState<[string, string][]>([]);
  const [chatLlm, setChatLlm] = useState("");

  useEffect(() => {
    getConfigOptions()
      .then((opts) => {
        // deep + quick 合并去重（按 model_id）
        const seen = new Set<string>();
        const merged: [string, string][] = [];
        for (const [label, id] of [
          ...opts.model_options.quick,
          ...opts.model_options.deep,
        ]) {
          if (!seen.has(id)) {
            seen.add(id);
            merged.push([label, id]);
          }
        }
        setChatModels(merged);
        const saved = localStorage.getItem("ta:chat_llm");
        const fallback = opts.configured_quick_llm ?? "";
        setChatLlm(saved && seen.has(saved) ? saved : fallback);
      })
      .catch(() => {
        /* 配置加载失败时下拉为空，发消息仍走后端默认 */
      });
  }, []);
```

- [ ] **Step 3: 发消息时传模型**

把 `streamChat(chatStreamUrl(sessionId), question, (e) => {...})`（约 line 225）的调用补上第 4、5 个参数。该调用没有用 signal，传 `undefined` 占位、再传 `chatLlm`：

```tsx
      await streamChat(
        chatStreamUrl(sessionId),
        question,
        (e) => {
          // ...（回调体保持原样）
        },
        undefined,
        chatLlm || undefined,
      );
```

- [ ] **Step 4: 加下拉 UI**

在 Chat 页输入框附近（页头或输入区上方）插入下拉。选一个合适容器，加入：

```tsx
          <label className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">模型</span>
            <select
              value={chatLlm}
              onChange={(e) => {
                setChatLlm(e.target.value);
                localStorage.setItem("ta:chat_llm", e.target.value);
              }}
              disabled={streaming}
              className="glass-control h-8 rounded-md px-2 font-mono text-xs text-foreground outline-none transition-colors focus:border-primary disabled:opacity-50"
            >
              {chatModels.map(([label, id]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
```

放置位置以不破坏现有布局为准（参考 Step 1 看到的页头/输入区结构）。

- [ ] **Step 5: 类型检查 + 手动验证**

Run: `cd webui && npx tsc --noEmit`（无类型错误）。
手动验证（后端在跑）：
1. 打开 Chat 页，确认出现模型下拉，默认选中配置的 quick 模型，选项为 deep+quick 合并去重列表。
2. 改选模型 → 刷新 → 记住。
3. 发一条消息，Network 面板确认 `POST /sessions/{id}/stream` 请求体含 `chat_llm` 为所选值；流式回复正常。

- [ ] **Step 6: 提交**

```bash
git add webui/app/chat/page.tsx
git commit -m "feat(webui): add model selector to chat page"
```

---

### Task 6: 收尾 — 全量 lint/测试 + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 全量 lint**

Run: `.venv/bin/python -m ruff check .`
Expected: 无新增告警（已有忽略规则照旧）。

- [ ] **Step 2: 全量测试（排除 integration）**

Run: `.venv/bin/python -m pytest -m "not integration"`
Expected: 全部 PASS。

- [ ] **Step 3: 更新 CHANGELOG**

在 `CHANGELOG.md` 的 `## [Unreleased]` 段 `### Added` 下追加（无该小节则新建）：

```markdown
- WebUI 支持在分析页与 Chat 页选择 LLM 模型（限当前已配置 provider 的 deep/quick 模型），选择记忆于浏览器 localStorage。
```

- [ ] **Step 4: 提交**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): note webui model selection feature"
```

---

## Self-Review

**Spec coverage:**
- 后端 `/api/config/options` 暴露 model_options → Task 1 ✅
- Chat `chat_llm` 字段 + 工厂接受 model + 路由透传 → Task 2 ✅
- 前端类型 + api/sse → Task 3 ✅
- 分析页 deep/quick 下拉 + localStorage → Task 4 ✅
- Chat 页合并下拉 + localStorage → Task 5 ✅
- 测试 + lint + CHANGELOG → Task 1/2 含后端测试，Task 6 收尾 ✅
- 分析后端不改动（spec 明确已打通）→ 无任务，符合预期 ✅

**Placeholder scan:** 无 TBD/TODO；每个代码步骤均给出完整代码。前端两处「保持原样」的回调体是明确指代现有代码、非占位。

**Type consistency:**
- `model_options` 三处一致：后端 `dict[str, list[tuple[str, str]]]`、TS `{ deep: [string,string][]; quick: [string,string][] }`、消费处按 `[label, id]` 解构 ✅
- `chat_llm` 三处一致：`ChatRequest.chat_llm: str | None`、`streamChat(..., model?)` body `chat_llm`、`stream_chat` 读 `req.chat_llm` ✅
- `real_chat_llm_factory(model=None)` 与所有 fake 工厂签名（`factory(model=None)`、`lambda model=None:`）及调用 `chat_llm_factory(model=req.chat_llm)` 一致 ✅
- localStorage key 一致：`ta:deep_think_llm`、`ta:quick_think_llm`、`ta:chat_llm` ✅
