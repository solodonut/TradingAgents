# ETF 诊断页:供应商多选 + 选择持久化 + 功能说明 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `/etf/diagnostics` 页面支持多选供应商(后端跳过未选的、不发请求)、记住上次选择,并为每个功能显示一句中文说明。

**Architecture:** 后端 `diagnostics.py` 新增 `METHOD_DESC` 与 `build_meta()`,`iter_probes`/`count_probes` 增加可选 `vendors` 过滤;SSE 路由加 `?vendors=` 参数、新增 `GET /etf/meta` 元数据端点。前端首屏拉 meta 渲染勾选框(localStorage∩可用供应商),SSE URL 带上选中供应商,结果按 `group → method` 二级分组、method 挂说明。

**Tech Stack:** Python 3.10 / FastAPI / sse-starlette;Next.js 16 / React 19 / TypeScript;`node --test` (前端纯函数)+ pytest(后端)。

## Global Constraints

- Python 命令一律用 `.venv/bin/python`(系统 python 可能是 3.9,会崩)。
- 后端数据探测层遵守 **never-raises**:诊断代码不外抛,异常转状态(已由 `probe_cell` 保证,本次不改)。
- 诊断保持**只读**:不改全局 config、不加锁、不写 checkpoint。
- 后端过滤语义:`vendors=None`(或空)= 全跑;未知供应商名静默忽略。
- 提交规范:Conventional Commits;完工同步 `CHANGELOG.md`(Keep a Changelog)。
- 收尾手动验证:`.venv/bin/ruff check .` + `.venv/bin/pytest -m "not integration"`;前端 `npm run lint` + `npm run build`。
- 改前端前先读 `webui/node_modules/next/dist/docs/`(Next.js 16 与训练数据有破坏性差异)。

---

### Task 1: 后端 —— METHOD_DESC、供应商过滤、build_meta

**Files:**
- Modify: `tradingagents/dataflows/diagnostics.py`
- Test: `tests/dataflows/test_diagnostics.py`

**Interfaces:**
- Consumes:`VENDOR_METHODS`(`dict[str, dict[str, impl]]`)、`METHOD_GROUP`(已存在)。
- Produces:
  - `METHOD_DESC: dict[str, str]` —— 覆盖 `METHOD_GROUP` 全部 14 个 key。
  - `iter_probes(code: str, ref_date: str, vendors: set[str] | None = None) -> Iterator[CellResult]`
  - `count_probes(vendors: set[str] | None = None) -> int`
  - `build_meta() -> dict` —— 返回 `{"vendors": list[str](已排序), "methods": [{"name","group","desc"}, ...]}`,methods 按 `METHOD_GROUP` 插入顺序。

- [ ] **Step 1: 写失败测试**

在 `tests/dataflows/test_diagnostics.py` 末尾追加:

```python
def test_method_desc_covers_every_method():
    from tradingagents.dataflows.diagnostics import METHOD_DESC, METHOD_GROUP

    assert set(METHOD_DESC) == set(METHOD_GROUP)
    assert all(METHOD_DESC[m].strip() for m in METHOD_GROUP)


def test_count_probes_with_vendors_subset():
    from tradingagents.dataflows.diagnostics import count_probes
    from tradingagents.dataflows.interface import VENDOR_METHODS

    only_tushare = sum(1 for vs in VENDOR_METHODS.values() if "tushare" in vs)
    assert count_probes(vendors={"tushare"}) == only_tushare
    assert count_probes(vendors=None) == count_probes()
    assert count_probes(vendors=set()) == 0


def test_iter_probes_filters_by_vendor(monkeypatch):
    from tradingagents.dataflows.diagnostics import iter_probes
    from tradingagents.dataflows.interface import VENDOR_METHODS

    for vendors in VENDOR_METHODS.values():
        for vendor in vendors:
            monkeypatch.setitem(vendors, vendor, lambda *a, **k: "stub")

    cells = list(iter_probes("510300.SS", "2026-07-13", vendors={"tushare"}))
    assert cells, "至少应有若干 tushare 格子"
    assert {c.vendor for c in cells} == {"tushare"}
    assert list(iter_probes("510300.SS", "2026-07-13", vendors=set())) == []


def test_build_meta_shape():
    from tradingagents.dataflows.diagnostics import build_meta
    from tradingagents.dataflows.interface import VENDOR_METHODS

    meta = build_meta()
    expected_vendors = sorted({v for vs in VENDOR_METHODS.values() for v in vs})
    assert meta["vendors"] == expected_vendors
    names = [m["name"] for m in meta["methods"]]
    assert set(names) == set(VENDOR_METHODS)
    assert all(m["desc"].strip() and m["group"] for m in meta["methods"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/dataflows/test_diagnostics.py -q`
Expected: FAIL(`ImportError: cannot import name 'METHOD_DESC'` / `build_meta`,以及 `count_probes()` 不接受 `vendors`)。

- [ ] **Step 3: 实现**

在 `tradingagents/dataflows/diagnostics.py` 中,`METHOD_GROUP` 定义之后新增 `METHOD_DESC`:

```python
# 每个方法一句中文说明,展示在诊断页。key 必须与 METHOD_GROUP 一致(测试保证)。
METHOD_DESC: dict[str, str] = {
    "get_stock_data": "日线 OHLCV 历史行情",
    "get_indicators": "技术指标(如 close_50_sma)",
    "get_etf_profile": "ETF 基本档案(规模 / 费率 / 跟踪指数)",
    "get_etf_intraday": "ETF 分时行情(默认 5min)",
    "get_etf_news": "ETF 相关新闻",
    "get_news": "标的相关新闻",
    "get_fundamentals": "基本面概况",
    "get_balance_sheet": "资产负债表(年报)",
    "get_cashflow": "现金流量表(年报)",
    "get_income_statement": "利润表(年报)",
    "get_insider_transactions": "内部人交易",
    "get_global_news": "全球宏观新闻",
    "get_macro_indicators": "宏观经济指标(如 CPI)",
    "get_prediction_markets": "预测市场行情(Polymarket)",
}
```

把 `iter_probes` 与 `count_probes` 替换为带 `vendors` 过滤的版本,并新增 `build_meta`(放在 `count_probes` 之后):

```python
def iter_probes(
    code: str, ref_date: str, vendors: set[str] | None = None
) -> Iterator[CellResult]:
    """串行遍历 (method, vendor) 格子。vendors=None 跑全部;否则只跑选中的供应商。

    串行是刻意的:避免并发触发限流、便于逐格计时。
    """
    for method, method_vendors in VENDOR_METHODS.items():
        for vendor in method_vendors:
            if vendors is not None and vendor not in vendors:
                continue
            yield probe_cell(method, vendor, code, ref_date)


def count_probes(vendors: set[str] | None = None) -> int:
    if vendors is None:
        return sum(len(v) for v in VENDOR_METHODS.values())
    return sum(1 for vs in VENDOR_METHODS.values() for v in vs if v in vendors)


def build_meta() -> dict:
    """供前端渲染:全部供应商(去重排序)+ 每个方法的分区与说明。纯读、无网络。"""
    vendors = sorted({v for vs in VENDOR_METHODS.values() for v in vs})
    methods = [
        {"name": m, "group": METHOD_GROUP[m], "desc": METHOD_DESC[m]}
        for m in METHOD_GROUP
    ]
    return {"vendors": vendors, "methods": methods}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/dataflows/test_diagnostics.py -q`
Expected: PASS(全部,含新增 4 个)。

- [ ] **Step 5: 提交**

```bash
git add tradingagents/dataflows/diagnostics.py tests/dataflows/test_diagnostics.py
git commit -m "feat(diagnostics): add METHOD_DESC, vendor filtering and build_meta"
```

---

### Task 2: API 路由 —— meta 端点 + SSE vendors 参数

**Files:**
- Modify: `api/routes/diagnostics.py`
- Modify: `tests/webui/test_smoke.py`(现有 fake 需接受 `vendors` 形参)

**Interfaces:**
- Consumes:`iter_probes(code, ref_date, vendors)`、`count_probes(vendors)`、`build_meta()`(Task 1)。
- Produces:
  - `GET /api/diagnostics/etf/meta` → `build_meta()` 的 JSON。
  - `GET /api/diagnostics/etf/{code}?vendors=a,b` → SSE,vendors 逗号分隔,空/缺省=全跑。
- **注意路由顺序**:`/etf/meta` 必须在 `/etf/{code}` **之前**声明,否则 `{code}` 会捕获 `"meta"`。

- [ ] **Step 1: 写失败测试**

改现有 `test_diagnostics_route_registered_and_streams`:让 `fake_iter` 接受 `vendors`、`diagnostics_count` 接受 `vendors`,并追加断言 vendors 透传。然后新增 meta 端点测试与 vendors 透传测试。用下面整体替换 `tests/webui/test_smoke.py` 第 43–77 行的函数体及其后:

```python
def test_diagnostics_route_registered_and_streams():
    from dataclasses import dataclass

    from api.main import app

    @dataclass
    class _Cell:
        method: str
        vendor: str
        group: str
        status: str
        elapsed_ms: float
        raw: str
        error_type: str | None

    def fake_iter(code, ref_date, vendors=None):
        yield _Cell("get_etf_profile", "tushare", "ETF 核心", "ok", 1.0, "hi", None)
        yield _Cell("get_etf_profile", "akshare", "ETF 核心", "no_perm", 2.0, "积分不足", None)

    app.state.diagnostics_probe_iter = fake_iter
    app.state.diagnostics_count = lambda vendors=None: 2
    try:
        client = TestClient(app)
        r = client.get("/api/diagnostics/etf/510300.SS?ref_date=2026-07-13")
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        body = r.text
        assert "event: start" in body
        assert body.count("event: cell") == 2
        assert "event: done" in body
        assert "no_perm" in body
    finally:
        app.state.diagnostics_probe_iter = None
        app.state.diagnostics_count = None


def test_diagnostics_vendors_param_passed_through():
    from dataclasses import dataclass

    from api.main import app

    @dataclass
    class _Cell:
        method: str
        vendor: str
        group: str
        status: str
        elapsed_ms: float
        raw: str
        error_type: str | None

    seen = {}

    def fake_iter(code, ref_date, vendors=None):
        seen["iter"] = vendors
        yield _Cell("get_etf_profile", "tushare", "ETF 核心", "ok", 1.0, "hi", None)

    def fake_count(vendors=None):
        seen["count"] = vendors
        return 1

    app.state.diagnostics_probe_iter = fake_iter
    app.state.diagnostics_count = fake_count
    try:
        client = TestClient(app)
        r = client.get("/api/diagnostics/etf/510300.SS?vendors=tushare,akshare")
        assert r.status_code == 200
        _ = r.text  # drain the stream so the generator runs
        assert seen["iter"] == {"tushare", "akshare"}
        assert seen["count"] == {"tushare", "akshare"}
    finally:
        app.state.diagnostics_probe_iter = None
        app.state.diagnostics_count = None


def test_diagnostics_meta_endpoint():
    from api.main import app

    client = TestClient(app)
    r = client.get("/api/diagnostics/etf/meta")
    assert r.status_code == 200
    data = r.json()
    assert data["vendors"], "vendors 非空"
    assert data["methods"], "methods 非空"
    assert all(m["desc"].strip() for m in data["methods"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/webui/test_smoke.py -q`
Expected: FAIL —— vendors 透传断言失败(路由还没解析/透传 vendors),且 `/etf/meta` 返回 404 或被 `{code}` 当成 code。

- [ ] **Step 3: 实现**

用下面整体替换 `api/routes/diagnostics.py` 中 `from ... import` 之后的路由部分(新增 meta 端点在前、SSE 加 vendors):

```python
from tradingagents.dataflows.diagnostics import build_meta, count_probes, iter_probes

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("/etf/meta")
def etf_diagnostics_meta() -> dict:
    """供应商名单 + 每个方法的分区与说明。纯读、无网络,不走 app.state 注入。"""
    return build_meta()


@router.get("/etf/{code}")
def stream_etf_diagnostics(
    code: str,
    request: Request,
    ref_date: str | None = Query(None),
    vendors: str | None = Query(None),
) -> EventSourceResponse:
    rd = ref_date or date.today().isoformat()
    # 逗号分隔;空 / 缺省 = 全跑(None)。未知供应商名由 iter/count 静默忽略。
    vendor_set = {v.strip() for v in vendors.split(",") if v.strip()} if vendors else None
    # tests inject fakes via app.state; production uses the real matrix.
    probe_iter = getattr(request.app.state, "diagnostics_probe_iter", None) or iter_probes
    count_fn = getattr(request.app.state, "diagnostics_count", None) or count_probes

    def event_generator():
        counts = {"ok": 0, "no_data": 0, "no_perm": 0, "unavailable": 0}
        t0 = time.time()
        yield {
            "event": "start",
            "data": json.dumps({"total": count_fn(vendor_set), "code": code, "ref_date": rd}),
        }
        for cell in probe_iter(code, rd, vendor_set):
            counts[cell.status] = counts.get(cell.status, 0) + 1
            yield {"event": "cell", "data": json.dumps(asdict(cell))}
        counts["elapsed_ms"] = (time.time() - t0) * 1000
        yield {"event": "done", "data": json.dumps(counts)}

    return EventSourceResponse(event_generator())
```

（顶部 `import json / time`、`from dataclasses import asdict`、`from datetime import date`、`from fastapi import APIRouter, Query, Request`、`from sse_starlette.sse import EventSourceResponse` 保持不变。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/webui/test_smoke.py -q`
Expected: PASS(含新增 2 个测试)。

- [ ] **Step 5: 提交**

```bash
git add api/routes/diagnostics.py tests/webui/test_smoke.py
git commit -m "feat(api): add diagnostics meta endpoint and SSE vendors filter"
```

---

### Task 3: 前端 lib —— 供应商选择解析(纯函数,TDD)

**Files:**
- Create: `webui/lib/etf-diagnostics.ts`
- Test: `webui/lib/etf-diagnostics.test.ts`

**Interfaces:**
- Produces:`resolveVendorSelection(saved: string[] | null, available: string[]): string[]`
  - `saved` 为 `null`(无记录)→ 返回全部 `available` 的副本。
  - 否则取 `saved ∩ available`(保持 saved 中出现顺序);若交集为空 → 返回全部 `available`(避免卡在“全不选”)。

- [ ] **Step 1: 写失败测试**

Create `webui/lib/etf-diagnostics.test.ts`:

```ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { resolveVendorSelection } from "./etf-diagnostics.ts";

const ALL = ["akshare", "tushare", "yfinance"];

test("null saved → all available", () => {
  assert.deepEqual(resolveVendorSelection(null, ALL), ALL);
});

test("subset preserved and filtered to available", () => {
  assert.deepEqual(resolveVendorSelection(["tushare", "akshare"], ALL), ["tushare", "akshare"]);
});

test("stale saved entries dropped", () => {
  assert.deepEqual(resolveVendorSelection(["tushare", "gone"], ALL), ["tushare"]);
});

test("all-stale saved → all available", () => {
  assert.deepEqual(resolveVendorSelection(["gone", "x"], ALL), ALL);
});

test("empty saved → all available", () => {
  assert.deepEqual(resolveVendorSelection([], ALL), ALL);
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd webui && node --no-warnings --test --experimental-strip-types lib/etf-diagnostics.test.ts`
Expected: FAIL(`Cannot find module './etf-diagnostics.ts'`)。

- [ ] **Step 3: 实现**

Create `webui/lib/etf-diagnostics.ts`:

```ts
/** 解析要勾选的供应商:localStorage 记录 ∩ 当前可用供应商。
 *  无记录 → 全选;交集为空(记录全过期)→ 回退全选,避免“全不选”死锁。 */
export function resolveVendorSelection(
  saved: string[] | null,
  available: string[],
): string[] {
  if (saved === null) return [...available];
  const availableSet = new Set(available);
  const kept = saved.filter((v) => availableSet.has(v));
  return kept.length ? kept : [...available];
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd webui && node --no-warnings --test --experimental-strip-types lib/etf-diagnostics.test.ts`
Expected: PASS(5 个)。

- [ ] **Step 5: 提交**

```bash
git add webui/lib/etf-diagnostics.ts webui/lib/etf-diagnostics.test.ts
git commit -m "feat(webui): add resolveVendorSelection helper for diagnostics"
```

---

### Task 4: 前端 —— meta 类型 + API 客户端 vendors 参数

**Files:**
- Modify: `webui/lib/types.ts:203-234`(在 Diagnostic 区块内追加)
- Modify: `webui/lib/api.ts`(import、`etfDiagnosticsStreamUrl`、`subscribeEtfDiagnostics`、新增 `getEtfDiagnosticsMeta`)

**Interfaces:**
- Consumes:`GET /api/diagnostics/etf/meta`(Task 2)。
- Produces:
  - 类型 `DiagnosticMethodMeta { name: string; group: string; desc: string }`、`DiagnosticMeta { vendors: string[]; methods: DiagnosticMethodMeta[] }`。
  - `getEtfDiagnosticsMeta(): Promise<DiagnosticMeta>`
  - `etfDiagnosticsStreamUrl(code, refDate?, vendors?: string[])`
  - `subscribeEtfDiagnostics(code, refDate, vendors: string[], onEvent, onClose, onError)`

- [ ] **Step 1: 加 meta 类型**

在 `webui/lib/types.ts` 的 `DiagnosticEvent` 定义之后追加:

```ts
export interface DiagnosticMethodMeta {
  name: string;
  group: string;
  desc: string;
}

export interface DiagnosticMeta {
  vendors: string[];
  methods: DiagnosticMethodMeta[];
}
```

- [ ] **Step 2: 改 api.ts**

在 `webui/lib/api.ts` 顶部 import 的 `DiagnosticEvent,` 下一行加入 `DiagnosticMeta,`。

用下面整体替换 `etfDiagnosticsStreamUrl` 与 `subscribeEtfDiagnostics` 的签名相关部分,并在其上方新增 `getEtfDiagnosticsMeta`(替换第 240–253 行区间,`handler` 及之后保持不变):

```ts
export async function getEtfDiagnosticsMeta(): Promise<DiagnosticMeta> {
  const r = await fetch(`${BASE}/api/diagnostics/etf/meta`);
  if (!r.ok) throw new Error("failed to load diagnostics meta");
  return r.json();
}

export function etfDiagnosticsStreamUrl(
  code: string,
  refDate?: string,
  vendors?: string[],
): string {
  const url = new URL(`${BASE}/api/diagnostics/etf/${encodeURIComponent(code)}`);
  if (refDate) url.searchParams.set("ref_date", refDate);
  if (vendors && vendors.length) url.searchParams.set("vendors", vendors.join(","));
  return url.toString();
}

export function subscribeEtfDiagnostics(
  code: string,
  refDate: string | undefined,
  vendors: string[],
  onEvent: (e: DiagnosticEvent) => void,
  onClose: () => void,
  onError: (message: string) => void,
): () => void {
  const es = new EventSource(etfDiagnosticsStreamUrl(code, refDate, vendors));
```

（原 `const es = new EventSource(etfDiagnosticsStreamUrl(code, refDate));` 这一行被上面替换成带 vendors 的版本;`handler`、`addEventListener`、`return () => es.close()` 等后续不变。）

- [ ] **Step 3: 验证类型/构建**

Run: `cd webui && npx tsc --noEmit`
Expected: 仅 `page.tsx` 因 `subscribeEtfDiagnostics` 新增必填参数而报错(下一 Task 修复);`api.ts`/`types.ts` 本身无错。
（若想零报错,可与 Task 5 合并提交;这里允许 page.tsx 暂时报错。）

- [ ] **Step 4: 提交**

```bash
git add webui/lib/types.ts webui/lib/api.ts
git commit -m "feat(webui): add diagnostics meta client and vendors stream param"
```

---

### Task 5: 前端页面 —— 勾选框、持久化、二级分组说明

**Files:**
- Modify: `webui/app/etf/diagnostics/page.tsx`(整体重写组件)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes:`getEtfDiagnosticsMeta`、`subscribeEtfDiagnostics(code, refDate, vendors, ...)`(Task 4);`resolveVendorSelection`(Task 3);`DiagnosticMeta`、`DiagnosticCell` 等类型。
- localStorage key:`"etf-diag-vendors"`(JSON 字符串数组)。

- [ ] **Step 1: 读 Next.js 16 文档**

先浏览 `webui/node_modules/next/dist/docs/` 中与 client component / `use client` / hooks 相关章节,确认 `useEffect`+localStorage 的用法无破坏性差异。

- [ ] **Step 2: 重写 page.tsx**

用以下内容整体替换 `webui/app/etf/diagnostics/page.tsx`:

```tsx
"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { getEtfDiagnosticsMeta, subscribeEtfDiagnostics } from "@/lib/api";
import { resolveVendorSelection } from "@/lib/etf-diagnostics";
import type {
  DiagnosticCell,
  DiagnosticMeta,
  DiagnosticStatus,
  DiagnosticSummary,
} from "@/lib/types";

const GROUPS = ["ETF 核心", "股票基本面", "参考·与 ETF 无关"] as const;
const STORAGE_KEY = "etf-diag-vendors";

const STATUS_META: Record<DiagnosticStatus, { label: string; icon: string; cls: string }> = {
  ok: { label: "成功", icon: "✅", cls: "text-[#6affb0]" },
  no_data: { label: "无数据·输入不对", icon: "⚠️", cls: "text-[#ffcf70]" },
  no_perm: { label: "无权限", icon: "🔒", cls: "text-[#8ab4ff]" },
  unavailable: { label: "不可用", icon: "❌", cls: "text-[#ff6b6b]" },
};

function cellKey(method: string, vendor: string): string {
  return `${method}::${vendor}`;
}

function readSaved(): string[] | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((v) => typeof v === "string") : null;
  } catch {
    return null;
  }
}

export default function EtfDiagnosticsPage() {
  const [code, setCode] = useState("");
  const [refDate, setRefDate] = useState(new Date().toISOString().slice(0, 10));
  const [running, setRunning] = useState(false);
  const [total, setTotal] = useState(0);
  const [cells, setCells] = useState<Record<string, DiagnosticCell>>({});
  const [summary, setSummary] = useState<DiagnosticSummary | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [meta, setMeta] = useState<DiagnosticMeta | null>(null);
  const [metaError, setMetaError] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const closeRef = useRef<(() => void) | null>(null);

  // 首屏拉 meta,并用 localStorage∩可用供应商 初始化勾选。
  useEffect(() => {
    let alive = true;
    getEtfDiagnosticsMeta()
      .then((m) => {
        if (!alive) return;
        setMeta(m);
        setSelected(new Set(resolveVendorSelection(readSaved(), m.vendors)));
      })
      .catch(() => alive && setMetaError(true));
    return () => {
      alive = false;
    };
  }, []);

  const done = Object.keys(cells).length;

  // group → method(按 meta 顺序)→ 该 method 的 cells。
  const byMethod = useMemo(() => {
    const acc: Record<string, DiagnosticCell[]> = {};
    for (const c of Object.values(cells)) (acc[c.method] ??= []).push(c);
    return acc;
  }, [cells]);

  const methodsByGroup = useMemo(() => {
    const acc: Record<string, { name: string; desc: string }[]> = {};
    for (const m of meta?.methods ?? []) (acc[m.group] ??= []).push({ name: m.name, desc: m.desc });
    return acc;
  }, [meta]);

  function toggleVendor(v: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(v)) next.delete(v);
      else next.add(v);
      persist(next);
      return next;
    });
  }

  function setAll(on: boolean) {
    const next = on ? new Set(meta?.vendors ?? []) : new Set<string>();
    setSelected(next);
    persist(next);
  }

  function persist(next: Set<string>) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]));
    } catch {
      /* ignore quota / private mode */
    }
  }

  function start() {
    if (!code.trim() || running || selected.size === 0) return;
    setCells({});
    setSummary(null);
    setTotal(0);
    setRunning(true);
    closeRef.current = subscribeEtfDiagnostics(
      code.trim(),
      refDate,
      [...selected],
      (e) => {
        if (e.event === "start") setTotal(e.data.total);
        else if (e.event === "cell")
          setCells((prev) => ({ ...prev, [cellKey(e.data.method, e.data.vendor)]: e.data }));
        else if (e.event === "done") setSummary(e.data);
      },
      () => setRunning(false),
      () => setRunning(false),
    );
  }

  function stop() {
    closeRef.current?.();
    closeRef.current = null;
    setRunning(false);
  }

  const canRun = !!code.trim() && selected.size > 0;

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <h1 className="text-lg font-semibold">ETF 数据端点诊断</h1>

      <div className="glass flex flex-col gap-3 rounded-lg p-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            ETF 代码
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="510300.SS"
              className="rounded-md border border-border/60 bg-black/20 px-2 py-1 font-mono text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            参考日期
            <input
              type="date"
              value={refDate}
              onChange={(e) => setRefDate(e.target.value)}
              className="rounded-md border border-border/60 bg-black/20 px-2 py-1 font-mono text-sm"
            />
          </label>
          {running ? (
            <button
              onClick={stop}
              className="rounded-md border border-border/60 px-3 py-1.5 text-sm hover:text-primary"
            >
              停止 ({done}/{total})
            </button>
          ) : (
            <button
              onClick={start}
              disabled={!canRun}
              className="rounded-md border border-border/60 px-3 py-1.5 text-sm hover:text-primary disabled:opacity-40"
            >
              测试
            </button>
          )}
        </div>

        {/* 供应商多选 */}
        <div className="flex flex-col gap-2 border-t border-border/40 pt-3">
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>供应商</span>
            <button onClick={() => setAll(true)} className="hover:text-primary">
              全选
            </button>
            <button onClick={() => setAll(false)} className="hover:text-primary">
              清空
            </button>
            <span className="text-[11px]">已选 {selected.size}</span>
          </div>
          {metaError ? (
            <p className="text-xs text-[#ff6b6b]">供应商列表加载失败,请刷新页面重试。</p>
          ) : (
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              {(meta?.vendors ?? []).map((v) => (
                <label key={v} className="flex items-center gap-1.5 font-mono text-xs">
                  <input
                    type="checkbox"
                    checked={selected.has(v)}
                    onChange={() => toggleVendor(v)}
                  />
                  {v}
                </label>
              ))}
            </div>
          )}
          {!metaError && selected.size === 0 && (
            <p className="text-[11px] text-[#ffcf70]">至少选择一个供应商才能测试。</p>
          )}
        </div>
      </div>

      {summary && (
        <div className="glass flex flex-wrap gap-4 rounded-lg px-4 py-3 font-mono text-sm">
          <span className={STATUS_META.ok.cls}>✅ {summary.ok}</span>
          <span className={STATUS_META.no_data.cls}>⚠️ {summary.no_data}</span>
          <span className={STATUS_META.no_perm.cls}>🔒 {summary.no_perm}</span>
          <span className={STATUS_META.unavailable.cls}>❌ {summary.unavailable}</span>
          <span className="text-muted-foreground">
            用时 {(summary.elapsed_ms / 1000).toFixed(1)}s
          </span>
        </div>
      )}

      {GROUPS.map((group) => {
        const methods = (methodsByGroup[group] ?? []).filter((m) => byMethod[m.name]?.length);
        if (!methods.length) return null;
        return (
          <section key={group} className="glass rounded-lg p-4">
            <h2 className="mb-2 text-sm font-medium text-muted-foreground">{group}</h2>
            <div className="flex flex-col gap-3">
              {methods.map((m) => (
                <div key={m.name}>
                  <div className="flex items-baseline gap-2 font-mono text-xs">
                    <span className="font-medium">{m.name}</span>
                    <span className="text-[11px] text-muted-foreground">— {m.desc}</span>
                  </div>
                  <div className="mt-1 flex flex-col divide-y divide-border/40 pl-3">
                    {byMethod[m.name].map((c) => {
                      const k = cellKey(c.method, c.vendor);
                      const cm = STATUS_META[c.status];
                      return (
                        <div key={k} className="py-1.5">
                          <button
                            onClick={() => setExpanded(expanded === k ? null : k)}
                            className="flex w-full items-center gap-2 text-left font-mono text-xs"
                          >
                            <span className={cm.cls}>{cm.icon}</span>
                            <span className="w-28 truncate text-muted-foreground">{c.vendor}</span>
                            <span className="text-muted-foreground">{c.elapsed_ms.toFixed(0)}ms</span>
                          </button>
                          {expanded === k && (
                            <pre className="mt-1 max-h-72 overflow-auto rounded-md border border-border/60 bg-black/30 p-2 text-[11px] whitespace-pre-wrap">
                              {c.error_type ? `[${c.error_type}] ` : ""}
                              {c.raw}
                            </pre>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </main>
  );
}
```

- [ ] **Step 3: Lint + 类型 + 构建**

Run: `cd webui && npm run lint && npx tsc --noEmit && npm run build`
Expected: 全部通过、无 error。

- [ ] **Step 4: 手动验证(浏览器)**

启动:仓库根 `./dev.sh`(或分别起 API 与 web)。浏览 `http://localhost:3000/etf/diagnostics`:
1. 供应商勾选框出现,默认全选。
2. 取消勾选 `yfinance` 等 → 刷新页面 → 该勾选仍为取消(localStorage 生效)。
3. 只勾 `tushare`,输入 `510300.SS` 点测试 → 进度 total 只等于 tushare 的格子数,结果里 vendor 只有 tushare。
4. 每个功能显示 `方法名 — 说明`,同一功能的多个供应商缩进列在其下,功能名不再重复。
5. 全部取消 → 「测试」按钮禁用并提示。

- [ ] **Step 5: 更新 CHANGELOG 并提交**

在 `CHANGELOG.md` 的 `## [Unreleased]` → `### Added` 下新增:

```markdown
- ETF 诊断页支持多选供应商(后端跳过未选供应商、不发请求)、记住上次选择,并为每个数据功能显示一句中文说明。
```

```bash
git add webui/app/etf/diagnostics/page.tsx CHANGELOG.md
git commit -m "feat(webui): multi-select vendors, persist selection, per-method descriptions on ETF diagnostics"
```

---

## Self-Review 记录

- **Spec 覆盖**:决策 A(meta 端点/METHOD_DESC)→ Task 1+2+4;决策 B(后端 vendors 过滤)→ Task 1+2;决策 C(勾选框/持久化/二级分组说明)→ Task 3+4+5。测试点、错误处理(meta 失败提示、全不选禁用、未知 vendor 忽略)均落到任务。
- **占位符**:无 TODO/TBD;所有代码步骤含完整代码。
- **类型一致**:`subscribeEtfDiagnostics(code, refDate, vendors, onEvent, onClose, onError)` 在 Task 4 定义、Task 5 调用一致;`resolveVendorSelection`、`getEtfDiagnosticsMeta`、`build_meta`、`iter_probes(...,vendors)`、`count_probes(vendors)` 跨任务签名一致;localStorage key `"etf-diag-vendors"` 与 STORAGE_KEY 一致。
- **路由顺序**:Task 2 已显式要求 `/etf/meta` 在 `/etf/{code}` 之前声明。
```
