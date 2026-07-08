# WebUI 代码清单（Ticker Watchlist）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「新分析配置」的多代码 textarea 换成「单代码输入框 + 可持久化、可编辑、可排序的代码清单」，开始分析时按清单顺序入队。

**Architecture:** 后端新增只读接口 `GET /api/ticker/{code}` 薄包装既有 `resolve_instrument_identity`，返回代码对应公司名。前端 `ConfigCard` 用受控的 `TickerItem[]` 状态驱动清单，localStorage（key `ta:ticker_list`）持久化，添加时异步查名称；入队链路（`enqueueAnalysis` → `POST /api/queue`）原样复用，仅改 tickers 来源。

**Tech Stack:** FastAPI（后端路由）、pytest + TestClient（后端测试）、Next.js 16 / React 19 / Tailwind 4（前端，无新依赖）、lucide-react 图标。

## Global Constraints

- Python 一律用 `.venv/bin/python` 跑（系统 python 可能 <3.10 或 NumPy 1.x 冲突）。
- 后端数据/身份解析永不抛异常、fail-open：查不到返回空，不报错。
- 前端不引入拖拽库；排序用上/下按钮（沿用 `QueuePanel.tsx` 写法）。
- localStorage key 统一 `ta:` 前缀，内联读写，不新建封装层。
- Conventional Commits；维护 `CHANGELOG.md`（Keep a Changelog）。
- 收尾跑 `ruff check .` 和 `.venv/bin/python -m pytest -m "not integration"`。
- 改 `webui/` 前先看 `webui/node_modules/next/dist/docs/`（Next.js 16 与训练数据有破坏性差异）。

---

### Task 1: 后端名称查询接口 `GET /api/ticker/{code}`

**Files:**
- Create: `api/routes/ticker.py`
- Modify: `api/main.py`（在 queue router 注册之后追加 ticker router 注册，约第 119 行后）
- Test: `tests/webui/test_routes_ticker.py`

**Interfaces:**
- Consumes: `tradingagents.agents.utils.agent_utils.resolve_instrument_identity(ticker: str) -> dict`（含 `company_name` 键，fail-open，已带 lru_cache）。
- Produces: HTTP `GET /api/ticker/{code}` → JSON `{ "ticker": str, "name": str | None, "valid": bool }`。

- [ ] **Step 1: Write the failing test**

创建 `tests/webui/test_routes_ticker.py`：

```python
import api.routes.ticker as ticker_routes


def test_lookup_returns_name_when_resolved(client, monkeypatch):
    monkeypatch.setattr(
        ticker_routes,
        "resolve_instrument_identity",
        lambda code: {"company_name": "NVIDIA Corporation"},
    )
    resp = client.get("/api/ticker/NVDA")
    assert resp.status_code == 200
    assert resp.json() == {"ticker": "NVDA", "name": "NVIDIA Corporation", "valid": True}


def test_lookup_uppercases_and_strips(client, monkeypatch):
    seen = {}

    def fake(code):
        seen["code"] = code
        return {"company_name": "Apple Inc."}

    monkeypatch.setattr(ticker_routes, "resolve_instrument_identity", fake)
    resp = client.get("/api/ticker/aapl")
    assert resp.status_code == 200
    assert resp.json()["ticker"] == "AAPL"
    assert seen["code"] == "AAPL"


def test_lookup_invalid_returns_null_name_not_error(client, monkeypatch):
    monkeypatch.setattr(ticker_routes, "resolve_instrument_identity", lambda code: {})
    resp = client.get("/api/ticker/ZZZZ")
    assert resp.status_code == 200
    assert resp.json() == {"ticker": "ZZZZ", "name": None, "valid": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_ticker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.routes.ticker'`（route 尚未创建）。

- [ ] **Step 3: Create the route**

创建 `api/routes/ticker.py`：

```python
"""Ticker route: resolve a single code to its company name (read-only)."""

from fastapi import APIRouter

from tradingagents.agents.utils.agent_utils import resolve_instrument_identity

router = APIRouter(prefix="/api/ticker", tags=["ticker"])


@router.get("/{code}")
def lookup_ticker(code: str) -> dict:
    ticker = code.strip().upper()
    identity = resolve_instrument_identity(ticker)
    name = identity.get("company_name")
    return {"ticker": ticker, "name": name, "valid": bool(name)}
```

- [ ] **Step 4: Register the router in `api/main.py`**

在 queue router 注册之后（`app.include_router(queue_routes.router)` 一行后）追加：

```python
from api.routes import ticker as ticker_routes  # noqa: E402

app.include_router(ticker_routes.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_ticker.py -v`
Expected: PASS（3 个用例全过）。

- [ ] **Step 6: Commit**

```bash
git add api/routes/ticker.py api/main.py tests/webui/test_routes_ticker.py
git commit -m "feat(webui): add GET /api/ticker/{code} name lookup endpoint"
```

---

### Task 2: 前端 API 客户端 `lookupTicker`

**Files:**
- Modify: `webui/lib/api.ts`（在 `getConfigOptions` 之后追加，约第 20 行后）

**Interfaces:**
- Consumes: `GET /api/ticker/{code}`（Task 1）。
- Produces: `lookupTicker(code: string): Promise<{ ticker: string; name: string | null; valid: boolean }>`，失败不抛、返回 `valid:false`。

- [ ] **Step 1: 添加 `lookupTicker`**

在 `webui/lib/api.ts` 的 `getConfigOptions` 函数之后插入：

```ts
export async function lookupTicker(
  code: string,
): Promise<{ ticker: string; name: string | null; valid: boolean }> {
  const t = code.trim().toUpperCase();
  try {
    const r = await fetch(`${BASE}/api/ticker/${encodeURIComponent(t)}`);
    if (!r.ok) return { ticker: t, name: null, valid: false };
    return await r.json();
  } catch {
    return { ticker: t, name: null, valid: false };
  }
}
```

- [ ] **Step 2: 类型检查**

Run: `cd webui && npx tsc --noEmit`
Expected: 无新增报错（与改动前一致）。

- [ ] **Step 3: Commit**

```bash
git add webui/lib/api.ts
git commit -m "feat(webui): add lookupTicker API client"
```

---

### Task 3: ConfigCard 改为单代码输入 + 持久化清单

**Files:**
- Modify: `webui/components/ConfigCard.tsx`

**Interfaces:**
- Consumes: `lookupTicker`（Task 2）；既有 `onStart({ tickers: string[], ... })` 回调签名不变（`app/page.tsx` 第 576 行挂载、`onStart` 接 `enqueueAnalysis`，均无需改）。
- Produces: 无对外新接口；内部新增 `type TickerItem = { ticker: string; name: string }`，localStorage key `ta:ticker_list`。

说明：前端无单测框架，本任务以「类型检查通过 + 手动验收清单」作为验证，不写自动化测试。每个 step 仍是小步可回滚的编辑。

- [ ] **Step 1: 先读 Next.js 16 文档确认 client 组件约定**

Run: `ls webui/node_modules/next/dist/docs/`
查阅与 client component / hooks 相关的说明，确认 `"use client"` + `useState`/`useEffect` 用法无破坏性差异（本组件已是 `"use client"`，预期沿用即可）。

- [ ] **Step 2: 替换状态与 import**

在 `ConfigCard.tsx`：

1) 顶部 import 增补图标与 API（第 1-4 行区域）：

```ts
import { ChevronDown, ChevronUp, Cpu, LoaderCircle, Play, Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { lookupTicker } from "@/lib/api";
import type { AnalysisRequest, ConfigOptions } from "@/lib/types";
```

2) 在组件函数体顶部，新增类型与状态，替换原 `tickersText` 状态（原第 15 行）：

```ts
type TickerItem = { ticker: string; name: string };

// 原: const [tickersText, setTickersText] = useState("NVDA");
const [tickers, setTickers] = useState<TickerItem[]>([{ ticker: "NVDA", name: "" }]);
const [tickerInput, setTickerInput] = useState("");
```

3) 删除原 `parsedTickers`（原第 61-68 行）——清单顺序即提交顺序，不再从文本解析。

- [ ] **Step 3: 加 localStorage 读写 + 添加/删除/排序逻辑**

在已有的 models `useEffect` 之后新增「读」副作用，并加操作函数（放在 `toggle` 附近）：

```ts
// 挂载后从 localStorage 回填代码清单
useEffect(() => {
  const saved = localStorage.getItem("ta:ticker_list");
  if (!saved) return;
  try {
    const parsed = JSON.parse(saved);
    if (Array.isArray(parsed)) setTickers(parsed);
  } catch {
    // 损坏的数据：忽略，保留默认清单
  }
}, []);

// 清单每次变化都写回
useEffect(() => {
  localStorage.setItem("ta:ticker_list", JSON.stringify(tickers));
}, [tickers]);

const addTicker = async () => {
  const code = tickerInput.trim().toUpperCase();
  if (!code) return;
  if (tickers.some((t) => t.ticker === code)) {
    setTickerInput("");
    return; // 去重：已存在则忽略
  }
  setTickers((prev) => [...prev, { ticker: code, name: "" }]);
  setTickerInput("");
  const res = await lookupTicker(code);
  if (res.name) {
    setTickers((prev) =>
      prev.map((t) => (t.ticker === code ? { ...t, name: res.name as string } : t)),
    );
  }
};

const removeTicker = (code: string) =>
  setTickers((prev) => prev.filter((t) => t.ticker !== code));

const moveTicker = (index: number, delta: number) =>
  setTickers((prev) => {
    const next = [...prev];
    const j = index + delta;
    if (j < 0 || j >= next.length) return prev;
    [next[index], next[j]] = [next[j], next[index]];
    return next;
  });
```

- [ ] **Step 4: 改 onSubmit 的 tickers 来源**

把 `onSubmit`（原第 79-89 行）里的 `tickers: parsedTickers` 改为：

```ts
tickers: tickers.map((t) => t.ticker),
```

其余字段不变。

- [ ] **Step 5: 替换 Instrument 区块 UI（textarea → 输入框 + 清单）**

把原 `<textarea>` 那个 `<label>`（原第 180-189 行）替换为输入框 + 清单。日期 input 那个 `<label>` 保留。新的输入行 + 清单：

```tsx
<label className="space-y-1">
  <span className="sr-only">Ticker</span>
  <div className="flex gap-1.5">
    <input
      type="text"
      className="glass-control w-full rounded-md px-2.5 py-1.5 font-mono text-sm tracking-wide text-foreground placeholder:text-muted-foreground outline-none transition-colors focus:border-primary"
      value={tickerInput}
      onChange={(e) => setTickerInput(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          void addTicker();
        }
      }}
      placeholder="输入代码，如 NVDA / 159241.SZ"
    />
    <button
      type="button"
      onClick={() => void addTicker()}
      title="添加到清单"
      className="glass-control inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:border-primary"
    >
      <span className="sr-only">添加</span>
      <Plus className="size-4" aria-hidden="true" />
    </button>
  </div>
</label>

{tickers.length === 0 ? (
  <p className="px-0.5 py-2 text-xs text-muted-foreground">清单为空，添加代码后开始分析。</p>
) : (
  <ul className="space-y-1">
    {tickers.map((t, i) => (
      <li
        key={t.ticker}
        className="glass-control flex items-center gap-2 rounded-md px-2 py-1.5"
      >
        <span className="min-w-0 flex-1">
          <span className="font-mono text-sm text-foreground">{t.ticker}</span>
          {t.name ? (
            <span className="ml-2 truncate text-xs text-muted-foreground">{t.name}</span>
          ) : null}
        </span>
        <button
          type="button"
          onClick={() => moveTicker(i, -1)}
          disabled={i === 0}
          aria-label="上移"
          className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30 focus-visible:outline-none focus-visible:border-primary"
        >
          <ChevronUp className="size-3.5" aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={() => moveTicker(i, 1)}
          disabled={i === tickers.length - 1}
          aria-label="下移"
          className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30 focus-visible:outline-none focus-visible:border-primary"
        >
          <ChevronDown className="size-3.5" aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={() => removeTicker(t.ticker)}
          aria-label="移除"
          className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-destructive focus-visible:outline-none focus-visible:border-primary"
        >
          <X className="size-3.5" aria-hidden="true" />
        </button>
      </li>
    ))}
  </ul>
)}
```

注意：原 Instrument `<div className="grid ...">` 把 ticker 与日期并排。改为把输入行+清单放在上、日期放在下的单列布局即可（去掉两列 grid 或保留日期单独一行），按现有间距 `space-y` 处理，确保不破坏栅格。

- [ ] **Step 6: 改提交按钮的禁用与文案**

把按钮 `disabled`（原第 292 行）中的 `parsedTickers.length === 0` 改为 `tickers.length === 0`；文案里的 `parsedTickers.length` 改为 `tickers.length`：

```tsx
disabled={running || activeAnalysts.length === 0 || tickers.length === 0}
```

```tsx
{running
  ? "分析进行中"
  : tickers.length > 1
    ? `分析 ${tickers.length} 个标的`
    : "开始分析"}
```

- [ ] **Step 7: 类型检查**

Run: `cd webui && npx tsc --noEmit`
Expected: 无报错（确认已删除 `parsedTickers` 的所有引用、`tickersText` 不再被使用）。

- [ ] **Step 8: 手动验收（需后端 + 前端都启动：`./dev.sh`）**

逐条确认：
1. 输入 `NVDA` 回车/点 + → 出现一行，稍后名称补为「NVIDIA Corporation」。
2. 再输入一个无效代码（如 `ZZZZ`）→ 仍加入，名称留空，不报错。
3. 重复添加 `NVDA` → 不新增第二行。
4. 上移/下移/移除按钮正常，首行禁用上移、末行禁用下移。
5. 刷新页面 → 清单内容与顺序保留。
6. 点「开始分析」→ 队列按清单顺序逐个分析；分析进行中/结束后清单仍保留不变。

- [ ] **Step 9: Commit**

```bash
git add webui/components/ConfigCard.tsx
git commit -m "feat(webui): replace ticker textarea with persistent watchlist"
```

---

### Task 4: 收尾——CHANGELOG 与全量校验

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 更新 CHANGELOG**

在 `CHANGELOG.md` 的 `Unreleased` / 最新版本的 `Added` 下加一条：

```markdown
- WebUI 分析配置改用可持久化的代码清单：单代码输入框 + 自动带出公司名（`GET /api/ticker/{code}`）、可增删排序、localStorage 长期保存，开始分析按清单顺序入队。
```

- [ ] **Step 2: 后端 lint + 测试**

Run:
```bash
ruff check .
.venv/bin/python -m pytest -m "not integration" -q
```
Expected: ruff 无新增报错；pytest 全过（含新增 `test_routes_ticker.py`）。

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for ticker watchlist"
```

---

## Self-Review

**Spec coverage：**
- 后端名称接口 → Task 1 ✓
- 前端 API 客户端 → Task 2 ✓
- 单代码输入 + 清单 + 增删排序 + localStorage 持久化 + 分析后保留 → Task 3 ✓
- 按清单顺序入队（复用 enqueueAnalysis）→ Task 3 Step 4/6 ✓
- 查不到名称不阻断、localStorage 解析失败回退、去重、空清单禁用 → Task 1 Step 3 / Task 3 Step 3、6 ✓
- 测试（后端单测 + 前端手动验收）→ Task 1 / Task 3 Step 8 ✓
- CHANGELOG → Task 4 ✓

**Placeholder scan：** 无 TBD/TODO；所有代码步骤含完整代码与命令。

**Type consistency：** `TickerItem = { ticker; name }` 在 Task 3 各处一致；`lookupTicker` 返回 `{ticker,name,valid}` 与 Task 1 接口一致；`addTicker/removeTicker/moveTicker` 命名前后统一；`tickers`/`tickerInput` 替换掉了 `tickersText`/`parsedTickers`。
