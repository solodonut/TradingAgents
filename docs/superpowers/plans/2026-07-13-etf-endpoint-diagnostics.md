# ETF 数据端点诊断页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个诊断页,给定 ETF 代码逐格测试 `VENDOR_METHODS` 数据源矩阵的每个 `(方法, vendor)` 组合,通过 SSE 流式回填状态(✅成功 / ⚠️无数据·输入不对 / 🔒无权限 / ❌不可用)与原始返回内容。

**Architecture:** 后端新增只读模块 `tradingagents/dataflows/diagnostics.py`,**刻意绕过** `route_to_vendor`,直接调用 `VENDOR_METHODS[method][vendor]` 并按错误类型/哨兵前缀/关键词把结果四分类;`api/routes/diagnostics.py` 用 `sse_starlette.EventSourceResponse` 串行推 `start`→`cell`×N→`done`,不经单跑锁;前端 `webui/app/etf/diagnostics/page.tsx` 先按 `total` 铺骨架再逐格变色。

**Tech Stack:** Python 3.10+ / FastAPI / sse-starlette / pytest;Next.js 16 + React 19 + Tailwind 4 / EventSource。

## Global Constraints

- Python 命令一律用 `.venv/bin/python`、`.venv/bin/ruff`(系统 python 可能是 3.9,NumPy 冲突崩溃)。
- 诊断层**只读**:不写 checkpoint、不获取 `run_lock`、不调用 `set_config`、不改全局 config。
- 数据访问绕过 `route_to_vendor` 是本设计经用户批准的**唯一例外**;生产数据路径不改动。
- `probe_cell` 遵守「never raises」:捕获所有异常(含 `BaseException` 之外的常规 `Exception`),绝不外抛。
- 无 CI:收尾必须手动跑 `.venv/bin/ruff check .` 与 `.venv/bin/python -m pytest -m "not integration"` 全绿。
- 动 `webui/` 代码前先读 `webui/node_modules/next/dist/docs/`(Next.js 16 与训练数据有破坏性差异)。
- Conventional Commits;同步维护 `CHANGELOG.md`(Keep a Changelog)。仅用户明确要求时才提交/推送——但本计划每个 Task 末尾的 `git commit` 是计划的一部分,按 subagent-driven/executing-plans 流程执行。
- 回复一律中文。

## 文件结构

- Create `tradingagents/dataflows/diagnostics.py` — 分类函数 + 探测表 + `probe_cell`/`iter_probes`/`count_probes`。
- Create `tests/dataflows/test_diagnostics.py` — 分类与探测的单元测试。
- Create `api/routes/diagnostics.py` — SSE 路由 `GET /api/diagnostics/etf/{code}`。
- Modify `api/main.py` — 注册路由 + 两个 `app.state` 注入点默认值。
- Modify `tests/webui/test_smoke.py` — 追加诊断路由注册/SSE 结构 smoke 测试。
- Create `webui/app/etf/diagnostics/page.tsx` — 诊断页。
- Modify `webui/lib/types.ts` — 诊断事件类型。
- Modify `webui/lib/api.ts` — `etfDiagnosticsStreamUrl` + `subscribeEtfDiagnostics`。
- Modify `webui/app/etf/[ticker]/page.tsx` — 加一个跳转诊断页的入口链接。

---

### Task 1: 分类函数 `classify_result`

四态分类是最易错也最值得独立测试的纯逻辑,先单独做。

**Files:**
- Create: `tradingagents/dataflows/diagnostics.py`
- Test: `tests/dataflows/test_diagnostics.py`

**Interfaces:**
- Consumes: `tradingagents/dataflows/errors.py` 的 `NoMarketDataError`、`VendorRateLimitError`、`VendorNotConfiguredError`;`tradingagents/dataflows/interface.py` 的 `_NETWORK_ERRORS`。
- Produces:
  - `PERMISSION_HINTS: tuple[str, ...]`(小写关键词)
  - `classify_result(*, value: object | None = None, exc: BaseException | None = None) -> str`,返回 `"ok" | "no_data" | "no_perm" | "unavailable"`。

- [ ] **Step 1: 写失败测试**

创建 `tests/dataflows/test_diagnostics.py`:

```python
import pytest

from tradingagents.dataflows.diagnostics import classify_result
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)


def test_classify_ok_plain_string():
    assert classify_result(value="## 600519 收盘价 1680.0") == "ok"


def test_classify_ok_non_string_value():
    # 有的 vendor 返回 dict/DataFrame,非哨兵即视为成功
    assert classify_result(value={"close": 1.0}) == "ok"


def test_classify_no_data_sentinel_prefix():
    assert classify_result(value="NO_DATA_AVAILABLE: no rows") == "no_data"


def test_classify_no_data_from_exception():
    assert classify_result(exc=NoMarketDataError("510300.SS")) == "no_data"


def test_classify_no_data_news_error_sentinel():
    assert classify_result(value="Error fetching news for X") == "no_data"


def test_classify_no_perm_from_exception():
    assert classify_result(exc=VendorNotConfiguredError("no token")) == "no_perm"


def test_classify_no_perm_from_keyword():
    assert classify_result(value="抱歉,您的积分不足,无法访问该接口") == "no_perm"


def test_classify_unavailable_rate_limit():
    assert classify_result(exc=VendorRateLimitError("429")) == "unavailable"


def test_classify_unavailable_sentinel_prefix():
    assert classify_result(value="DATA_SOURCE_UNAVAILABLE: host down") == "unavailable"


def test_classify_unavailable_generic_exception():
    assert classify_result(exc=RuntimeError("boom")) == "unavailable"


def test_classify_sentinel_wins_over_keyword():
    # NO_DATA 前缀即使文本里含 "premium" 也判 no_data(前缀优先)
    assert classify_result(value="NO_DATA_AVAILABLE: premium only") == "no_data"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/dataflows/test_diagnostics.py -q`
Expected: FAIL —`ModuleNotFoundError: No module named 'tradingagents.dataflows.diagnostics'`(或 ImportError)。

- [ ] **Step 3: 写最小实现**

创建 `tradingagents/dataflows/diagnostics.py`:

```python
"""Read-only diagnostic probes over the VENDOR_METHODS data-source matrix.

Intentionally bypasses ``route_to_vendor`` (which only tries configured vendors
and stops at first success) to test EVERY (method, vendor) cell individually.
This is a deliberate, approved exception to the AGENTS.md rule that all data
access goes through ``route_to_vendor``. Read-only: no checkpoint, no run lock,
no config mutation. Honors the "never raises" contract — ``probe_cell`` catches
everything and reports a status instead of propagating.
"""

from __future__ import annotations

from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorRateLimitError,
)
from tradingagents.dataflows.interface import _NETWORK_ERRORS

# "无权限"启发式关键词(小写)。缺 key 通常抛 VendorNotConfiguredError(走异常路径);
# 积分/付费档问题往往由 vendor 以普通错误文本返回,只能靠关键词高亮。非权威判定——
# 原始返回全文始终保留供人工确认。集中在此一处维护。
PERMISSION_HINTS: tuple[str, ...] = (
    "积分不足",
    "权限不足",
    "没有权限",
    "抱歉,您没有",
    "请开通",
    "token 无效",
    "invalid token",
    "premium",
    "subscription",
    "api key",
    "apikey",
    "unauthorized",
    "forbidden",
    "401",
    "403",
)


def classify_result(*, value: object | None = None, exc: BaseException | None = None) -> str:
    """把一次探测的结果四分类:ok / no_data / no_perm / unavailable。

    异常类型优先;否则按返回字符串的哨兵前缀 / 关键词判定;非字符串返回视为 ok。
    """
    if exc is not None:
        if isinstance(exc, VendorNotConfiguredError):
            return "no_perm"
        if isinstance(exc, VendorRateLimitError):
            return "unavailable"
        if isinstance(exc, NoMarketDataError):
            return "no_data"
        if isinstance(exc, _NETWORK_ERRORS):
            return "unavailable"
        return "unavailable"

    if isinstance(value, str):
        if value.startswith("NO_DATA_AVAILABLE:"):
            return "no_data"
        if value.startswith(("DATA_SOURCE_UNAVAILABLE:", "DATA_SOURCE_DISABLED:")):
            return "unavailable"
        if value.startswith("Error fetching news"):
            return "no_data"
        low = value.lower()
        if any(hint in low for hint in PERMISSION_HINTS):
            return "no_perm"
        return "ok"

    return "ok"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/dataflows/test_diagnostics.py -q`
Expected: PASS(11 passed)。

- [ ] **Step 5: 提交**

```bash
git add tradingagents/dataflows/diagnostics.py tests/dataflows/test_diagnostics.py
git commit -m "feat(diagnostics): add four-state result classifier"
```

---

### Task 2: 探测表与遍历 `probe_cell` / `iter_probes` / `count_probes`

**Files:**
- Modify: `tradingagents/dataflows/diagnostics.py`
- Test: `tests/dataflows/test_diagnostics.py`

**Interfaces:**
- Consumes: Task 1 的 `classify_result`;`tradingagents/dataflows/interface.py` 的 `VENDOR_METHODS`。
- Produces:
  - `CellResult`(dataclass):字段 `method: str`、`vendor: str`、`group: str`、`status: str`、`elapsed_ms: float`、`raw: str`、`error_type: str | None`。
  - `METHOD_GROUP: dict[str, str]`(方法 → 3 个 UI 分区标签之一)。
  - `METHOD_PROBES: dict[str, Callable[[str, str], tuple]]`(`(code, ref_date)` → 实参元组)。
  - `probe_cell(method: str, vendor: str, code: str, ref_date: str) -> CellResult`
  - `iter_probes(code: str, ref_date: str) -> Iterator[CellResult]`
  - `count_probes() -> int`

> 说明:CellResult 用 `group`(3 个 UI 分区)取代设计文档里的 `category`(`get_category_for_method`)——因为同一 `news_data` 类别下 `get_news`→ETF核心 而 `get_global_news`→参考,类别无法唯一决定 UI 分区,故按方法直接映射分区。这是对 spec 的一处小修正,前端因此可直接用 `group` 渲染。

- [ ] **Step 1: 写失败测试**

在 `tests/dataflows/test_diagnostics.py` 追加:

```python
def test_count_probes_matches_matrix():
    from tradingagents.dataflows.diagnostics import count_probes
    from tradingagents.dataflows.interface import VENDOR_METHODS

    assert count_probes() == sum(len(v) for v in VENDOR_METHODS.values())


def test_iter_probes_covers_every_cell():
    from tradingagents.dataflows.diagnostics import count_probes, iter_probes

    cells = list(iter_probes("510300.SS", "2026-07-13"))
    assert len(cells) == count_probes()
    # 每格都有分区与耗时
    assert all(c.group for c in cells)
    assert all(c.elapsed_ms >= 0 for c in cells)


def test_probe_cell_ok(monkeypatch):
    from tradingagents.dataflows import diagnostics
    from tradingagents.dataflows.interface import VENDOR_METHODS

    monkeypatch.setitem(
        VENDOR_METHODS["get_etf_profile"], "tushare", lambda *a, **k: "## 招商中证白酒"
    )
    cell = diagnostics.probe_cell("get_etf_profile", "tushare", "510300.SS", "2026-07-13")
    assert cell.status == "ok"
    assert cell.error_type is None
    assert "白酒" in cell.raw
    assert cell.group == "ETF 核心"


def test_probe_cell_no_perm_from_exception(monkeypatch):
    from tradingagents.dataflows import diagnostics
    from tradingagents.dataflows.errors import VendorNotConfiguredError
    from tradingagents.dataflows.interface import VENDOR_METHODS

    def _raise(*a, **k):
        raise VendorNotConfiguredError("missing token")

    monkeypatch.setitem(VENDOR_METHODS["get_etf_profile"], "tushare", _raise)
    cell = diagnostics.probe_cell("get_etf_profile", "tushare", "510300.SS", "2026-07-13")
    assert cell.status == "no_perm"
    assert cell.error_type == "VendorNotConfiguredError"


def test_probe_cell_never_raises(monkeypatch):
    from tradingagents.dataflows import diagnostics
    from tradingagents.dataflows.interface import VENDOR_METHODS

    def _boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(VENDOR_METHODS["get_etf_profile"], "tushare", _boom)
    cell = diagnostics.probe_cell("get_etf_profile", "tushare", "510300.SS", "2026-07-13")
    assert cell.status == "unavailable"
    assert "kaboom" in cell.raw


def test_probe_cell_non_symbol_method_gets_fixed_args(monkeypatch):
    from tradingagents.dataflows import diagnostics
    from tradingagents.dataflows.interface import VENDOR_METHODS

    seen = {}

    def _spy(*args, **kwargs):
        seen["args"] = args
        return "ok text"

    monkeypatch.setitem(VENDOR_METHODS["get_prediction_markets"], "polymarket", _spy)
    cell = diagnostics.probe_cell(
        "get_prediction_markets", "polymarket", "510300.SS", "2026-07-13"
    )
    # prediction markets 与具体 ETF 无关:不注入 code
    assert "510300.SS" not in [str(a) for a in seen["args"]]
    assert cell.group == "参考·与 ETF 无关"


def test_iter_probes_is_read_only(monkeypatch):
    # 遍历(所有格子用不联网的桩)不得改动全局 config
    from tradingagents.dataflows import diagnostics
    from tradingagents.dataflows.config import get_config
    from tradingagents.dataflows.interface import VENDOR_METHODS

    for method, vendors in VENDOR_METHODS.items():
        for vendor in vendors:
            monkeypatch.setitem(vendors, vendor, lambda *a, **k: "stub")

    before = dict(get_config())
    list(diagnostics.iter_probes("510300.SS", "2026-07-13"))
    assert dict(get_config()) == before
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/dataflows/test_diagnostics.py -q`
Expected: FAIL —`ImportError: cannot import name 'probe_cell'`(或 `count_probes`/`iter_probes`)。

- [ ] **Step 3: 写最小实现**

在 `tradingagents/dataflows/diagnostics.py` 顶部 import 区补充,并在文件末尾追加实现:

```python
# --- 在现有 import 区补充 ---
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from tradingagents.dataflows.interface import VENDOR_METHODS

_MAX_RAW = 8000
_LOOKBACK_DAYS = 30


def _start(ref_date: str) -> str:
    return (datetime.strptime(ref_date, "%Y-%m-%d") - timedelta(days=_LOOKBACK_DAYS)).strftime(
        "%Y-%m-%d"
    )


# 方法 → UI 分区(3 组)。同一 TOOLS_CATEGORIES 类别下方法可能分属不同 UI 组,故按方法映射。
METHOD_GROUP: dict[str, str] = {
    "get_stock_data": "ETF 核心",
    "get_indicators": "ETF 核心",
    "get_etf_profile": "ETF 核心",
    "get_etf_intraday": "ETF 核心",
    "get_etf_news": "ETF 核心",
    "get_news": "ETF 核心",
    "get_fundamentals": "股票基本面",
    "get_balance_sheet": "股票基本面",
    "get_cashflow": "股票基本面",
    "get_income_statement": "股票基本面",
    "get_insider_transactions": "股票基本面",
    "get_global_news": "参考·与 ETF 无关",
    "get_macro_indicators": "参考·与 ETF 无关",
    "get_prediction_markets": "参考·与 ETF 无关",
}

# 各方法签名不一,把 (code, ref_date) 映射成每个方法的实参。参数与生产调用方保持一致格式
# (curr_date 用 YYYY-MM-DD)。非 symbol 方法(global_news/macro/prediction)用固定参数、不注入 code。
METHOD_PROBES: dict[str, Callable[[str, str], tuple]] = {
    "get_stock_data": lambda c, d: (c, _start(d), d),
    "get_indicators": lambda c, d: (c, "close_50_sma", d, _LOOKBACK_DAYS),
    "get_etf_profile": lambda c, d: (c, d),
    "get_etf_intraday": lambda c, d: (c, d, "5min"),
    "get_etf_news": lambda c, d: (c, _start(d), d),
    "get_news": lambda c, d: (c, _start(d), d),
    "get_fundamentals": lambda c, d: (c, d),
    "get_balance_sheet": lambda c, d: (c, "annual", d),
    "get_cashflow": lambda c, d: (c, "annual", d),
    "get_income_statement": lambda c, d: (c, "annual", d),
    "get_insider_transactions": lambda c, d: (c,),
    "get_global_news": lambda c, d: (d, 7, 20),
    "get_macro_indicators": lambda c, d: ("CPI", d, 90),
    "get_prediction_markets": lambda c, d: ("stock market", 10),
}


@dataclass
class CellResult:
    method: str
    vendor: str
    group: str
    status: str
    elapsed_ms: float
    raw: str
    error_type: str | None


def _truncate(text: str) -> str:
    return text if len(text) <= _MAX_RAW else text[:_MAX_RAW] + "… (truncated)"


def probe_cell(method: str, vendor: str, code: str, ref_date: str) -> CellResult:
    """直接调用 VENDOR_METHODS[method][vendor],返回四态结果。绝不外抛。"""
    impl = VENDOR_METHODS[method][vendor]
    func = impl[0] if isinstance(impl, list) else impl
    args = METHOD_PROBES[method](code, ref_date)

    t0 = time.time()
    value: object | None = None
    exc: BaseException | None = None
    try:
        value = func(*args)
    except Exception as e:  # noqa: BLE001 — 诊断层遵守 never-raises,把异常变成状态
        exc = e
    elapsed_ms = (time.time() - t0) * 1000

    status = classify_result(value=value, exc=exc)
    if exc is not None:
        raw = f"{type(exc).__name__}: {exc}"
        error_type = type(exc).__name__
    else:
        raw = value if isinstance(value, str) else repr(value)
        error_type = None

    return CellResult(
        method=method,
        vendor=vendor,
        group=METHOD_GROUP[method],
        status=status,
        elapsed_ms=elapsed_ms,
        raw=_truncate(raw),
        error_type=error_type,
    )


def iter_probes(code: str, ref_date: str) -> Iterator[CellResult]:
    """串行遍历所有 (method, vendor) 格子。串行是刻意的:避免并发触发限流、便于逐格计时。"""
    for method, vendors in VENDOR_METHODS.items():
        for vendor in vendors:
            yield probe_cell(method, vendor, code, ref_date)


def count_probes() -> int:
    return sum(len(vendors) for vendors in VENDOR_METHODS.values())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/dataflows/test_diagnostics.py -q`
Expected: PASS(18 passed)。

- [ ] **Step 5: lint + 提交**

```bash
.venv/bin/ruff check tradingagents/dataflows/diagnostics.py tests/dataflows/test_diagnostics.py
git add tradingagents/dataflows/diagnostics.py tests/dataflows/test_diagnostics.py
git commit -m "feat(diagnostics): add probe table, probe_cell and iter_probes"
```

---

### Task 3: SSE 路由 `GET /api/diagnostics/etf/{code}`

**Files:**
- Create: `api/routes/diagnostics.py`
- Modify: `api/main.py`(state 默认值 + 注册路由)
- Test: `tests/webui/test_smoke.py`

**Interfaces:**
- Consumes: Task 2 的 `iter_probes`、`count_probes`、`CellResult`。
- Produces: SSE 端点 `GET /api/diagnostics/etf/{code}?ref_date=YYYY-MM-DD`;事件 `start`/`cell`/`done`。测试注入点 `app.state.diagnostics_probe_iter`(签名 `(code, ref_date) -> Iterator[CellResult]`)、`app.state.diagnostics_count`(签名 `() -> int`)。

- [ ] **Step 1: 写失败 smoke 测试**

在 `tests/webui/test_smoke.py` 末尾追加:

```python
@pytest.mark.smoke
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

    def fake_iter(code, ref_date):
        yield _Cell("get_etf_profile", "tushare", "ETF 核心", "ok", 1.0, "hi", None)
        yield _Cell("get_etf_profile", "akshare", "ETF 核心", "no_perm", 2.0, "积分不足", None)

    app.state.diagnostics_probe_iter = fake_iter
    app.state.diagnostics_count = lambda: 2
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_smoke.py::test_diagnostics_route_registered_and_streams -q`
Expected: FAIL —404(路由未注册)或 `AttributeError`(state 缺字段)。

- [ ] **Step 3: 建路由文件**

创建 `api/routes/diagnostics.py`:

```python
"""ETF data-endpoint diagnostics: probe every VENDOR_METHODS cell over SSE.

Read-only and NOT gated by the single-run lock — it can run during an analysis.
"""

import json
import time
from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

from tradingagents.dataflows.diagnostics import count_probes, iter_probes

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("/etf/{code}")
def stream_etf_diagnostics(
    code: str,
    request: Request,
    ref_date: str | None = Query(None),
) -> EventSourceResponse:
    rd = ref_date or date.today().isoformat()
    # tests inject fakes via app.state; production uses the real matrix.
    probe_iter = getattr(request.app.state, "diagnostics_probe_iter", None) or iter_probes
    count_fn = getattr(request.app.state, "diagnostics_count", None) or count_probes

    def event_generator():
        counts = {"ok": 0, "no_data": 0, "no_perm": 0, "unavailable": 0}
        t0 = time.time()
        yield {
            "event": "start",
            "data": json.dumps({"total": count_fn(), "code": code, "ref_date": rd}),
        }
        for cell in probe_iter(code, rd):
            counts[cell.status] = counts.get(cell.status, 0) + 1
            yield {"event": "cell", "data": json.dumps(asdict(cell))}
        counts["elapsed_ms"] = (time.time() - t0) * 1000
        yield {"event": "done", "data": json.dumps(counts)}

    return EventSourceResponse(event_generator())
```

- [ ] **Step 4: 注册路由 + state 默认值**

在 `api/main.py` 的 `app.state` 定义区(`app.state.model_health = None` 之后)追加:

```python
app.state.diagnostics_probe_iter = None  # tests inject a fake probe iterator
app.state.diagnostics_count = None  # tests inject a fake total counter
```

在路由注册区末尾(`app.include_router(snapshots_routes.router)` 之后)追加:

```python
from api.routes import diagnostics as diagnostics_routes  # noqa: E402

app.include_router(diagnostics_routes.router)
```

- [ ] **Step 5: 跑 smoke 测试确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_smoke.py -q`
Expected: PASS(全部 smoke 通过,含新测试)。

- [ ] **Step 6: lint + 提交**

```bash
.venv/bin/ruff check api/routes/diagnostics.py api/main.py tests/webui/test_smoke.py
git add api/routes/diagnostics.py api/main.py tests/webui/test_smoke.py
git commit -m "feat(api): add ETF endpoint diagnostics SSE route"
```

---

### Task 4: 前端数据层(类型 + SSE 订阅)

**Files:**
- Modify: `webui/lib/types.ts`
- Modify: `webui/lib/api.ts`

**Interfaces:**
- Consumes: Task 3 的 SSE 事件 `start`/`cell`/`done`/`error`。
- Produces:
  - types: `DiagnosticStatus`、`DiagnosticCell`、`DiagnosticStart`、`DiagnosticSummary`、`DiagnosticEvent`。
  - api: `etfDiagnosticsStreamUrl(code: string, refDate?: string): string`;`subscribeEtfDiagnostics(code, refDate, onEvent, onClose, onError): () => void`(镜像现有 `subscribeServiceHealth`)。

- [ ] **Step 1: 先读 Next.js 16 文档(项目硬性要求)**

Run: `ls webui/node_modules/next/dist/docs/`
说明:本 Task 只改 `lib/`(纯 TS,不含 React/Next 渲染),仍按 CLAUDE.md 要求先扫一眼文档目录确认无相关破坏性变更,再动手。

- [ ] **Step 2: 加类型**

在 `webui/lib/types.ts` 末尾追加:

```ts
export type DiagnosticStatus = "ok" | "no_data" | "no_perm" | "unavailable";

export interface DiagnosticCell {
  method: string;
  vendor: string;
  group: string;
  status: DiagnosticStatus;
  elapsed_ms: number;
  raw: string;
  error_type: string | null;
}

export interface DiagnosticStart {
  total: number;
  code: string;
  ref_date: string;
}

export interface DiagnosticSummary {
  ok: number;
  no_data: number;
  no_perm: number;
  unavailable: number;
  elapsed_ms: number;
}

export type DiagnosticEvent =
  | { event: "start"; data: DiagnosticStart }
  | { event: "cell"; data: DiagnosticCell }
  | { event: "done"; data: DiagnosticSummary }
  | { event: "error"; data: { message: string } };
```

- [ ] **Step 3: 加 URL 构造与订阅函数**

在 `webui/lib/api.ts` 的 import 里把上述类型加入 `./types` 的 import 清单;然后在 `subscribeServiceHealth` 附近追加:

```ts
export function etfDiagnosticsStreamUrl(code: string, refDate?: string): string {
  const url = new URL(`${BASE}/api/diagnostics/etf/${encodeURIComponent(code)}`);
  if (refDate) url.searchParams.set("ref_date", refDate);
  return url.toString();
}

export function subscribeEtfDiagnostics(
  code: string,
  refDate: string | undefined,
  onEvent: (e: DiagnosticEvent) => void,
  onClose: () => void,
  onError: (message: string) => void,
): () => void {
  const es = new EventSource(etfDiagnosticsStreamUrl(code, refDate));
  const handler =
    (type: "start" | "cell" | "done" | "error") => (ev: MessageEvent) => {
      try {
        onEvent({ event: type, data: JSON.parse(ev.data) } as DiagnosticEvent);
      } catch {
        /* ignore malformed */
      }
    };
  (["start", "cell"] as const).forEach((t) => es.addEventListener(t, handler(t)));
  es.addEventListener("done", (ev) => {
    handler("done")(ev as MessageEvent);
    es.close();
    onClose();
  });
  es.addEventListener("error", (ev) => {
    // 服务端显式 error 事件带 data;连接层错误没有 data。
    if ((ev as MessageEvent).data) handler("error")(ev as MessageEvent);
  });
  es.onerror = () => {
    es.close();
    onError("诊断连接中断");
    onClose();
  };
  return () => es.close();
}
```

> 注意 `DiagnosticEvent` 等类型要加进 `api.ts` 顶部从 `./types` import 的具名清单里(与 `ServiceHealthEvent` 等并列),否则 TS 编译报未定义。

- [ ] **Step 4: 类型检查通过**

Run: `cd webui && npm run build`
Expected: 构建成功,无 TS 报错(本 Task 未加页面,仅类型与函数)。

- [ ] **Step 5: 提交**

```bash
git add webui/lib/types.ts webui/lib/api.ts
git commit -m "feat(webui): add ETF diagnostics SSE client and types"
```

---

### Task 5: 前端诊断页 + 导航入口

**Files:**
- Create: `webui/app/etf/diagnostics/page.tsx`
- Modify: `webui/app/etf/[ticker]/page.tsx`(加一个入口链接)

**Interfaces:**
- Consumes: Task 4 的 `subscribeEtfDiagnostics` 及 `DiagnosticCell`/`DiagnosticSummary`/`DiagnosticStart` 类型。

- [ ] **Step 1: 先读 Next.js 16 文档(硬性要求)**

Run: `ls webui/node_modules/next/dist/docs/` 并浏览与 `"use client"`、App Router page、`useSearchParams` 相关文档;确认 Next 16 客户端组件与事件订阅写法无破坏性差异,再动手。

- [ ] **Step 2: 建诊断页**

创建 `webui/app/etf/diagnostics/page.tsx`(复用 `glass rounded-lg` / `border-border/60` / `text-muted-foreground` / `font-mono` 约定):

```tsx
"use client";

import { useMemo, useRef, useState } from "react";

import { subscribeEtfDiagnostics } from "@/lib/api";
import type { DiagnosticCell, DiagnosticStatus, DiagnosticSummary } from "@/lib/types";

const GROUPS = ["ETF 核心", "股票基本面", "参考·与 ETF 无关"] as const;

const STATUS_META: Record<DiagnosticStatus, { label: string; icon: string; cls: string }> = {
  ok: { label: "成功", icon: "✅", cls: "text-[#6affb0]" },
  no_data: { label: "无数据·输入不对", icon: "⚠️", cls: "text-[#ffcf70]" },
  no_perm: { label: "无权限", icon: "🔒", cls: "text-[#8ab4ff]" },
  unavailable: { label: "不可用", icon: "❌", cls: "text-[#ff6b6b]" },
};

function cellKey(method: string, vendor: string): string {
  return `${method}::${vendor}`;
}

export default function EtfDiagnosticsPage() {
  const [code, setCode] = useState("");
  const [refDate, setRefDate] = useState(new Date().toISOString().slice(0, 10));
  const [running, setRunning] = useState(false);
  const [total, setTotal] = useState(0);
  const [cells, setCells] = useState<Record<string, DiagnosticCell>>({});
  const [summary, setSummary] = useState<DiagnosticSummary | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const closeRef = useRef<(() => void) | null>(null);

  const done = Object.keys(cells).length;

  const grouped = useMemo(() => {
    const byGroup: Record<string, DiagnosticCell[]> = {};
    for (const c of Object.values(cells)) (byGroup[c.group] ??= []).push(c);
    return byGroup;
  }, [cells]);

  function start() {
    if (!code.trim() || running) return;
    setCells({});
    setSummary(null);
    setTotal(0);
    setRunning(true);
    closeRef.current = subscribeEtfDiagnostics(
      code.trim(),
      refDate,
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

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <h1 className="text-lg font-semibold">ETF 数据端点诊断</h1>

      <div className="glass flex flex-wrap items-end gap-3 rounded-lg p-4">
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
            disabled={!code.trim()}
            className="rounded-md border border-border/60 px-3 py-1.5 text-sm hover:text-primary disabled:opacity-40"
          >
            测试
          </button>
        )}
      </div>

      {summary && (
        <div className="glass flex flex-wrap gap-4 rounded-lg px-4 py-3 font-mono text-sm">
          <span className={STATUS_META.ok.cls}>✅ {summary.ok}</span>
          <span className={STATUS_META.no_data.cls}>⚠️ {summary.no_data}</span>
          <span className={STATUS_META.no_perm.cls}>🔒 {summary.no_perm}</span>
          <span className={STATUS_META.unavailable.cls}>❌ {summary.unavailable}</span>
          <span className="text-muted-foreground">用时 {(summary.elapsed_ms / 1000).toFixed(1)}s</span>
        </div>
      )}

      {GROUPS.filter((g) => grouped[g]?.length).map((group) => (
        <section key={group} className="glass rounded-lg p-4">
          <h2 className="mb-2 text-sm font-medium text-muted-foreground">{group}</h2>
          <div className="flex flex-col divide-y divide-border/40">
            {grouped[group].map((c) => {
              const k = cellKey(c.method, c.vendor);
              const meta = STATUS_META[c.status];
              return (
                <div key={k} className="py-1.5">
                  <button
                    onClick={() => setExpanded(expanded === k ? null : k)}
                    className="flex w-full items-center gap-2 text-left font-mono text-xs"
                  >
                    <span className={meta.cls}>{meta.icon}</span>
                    <span className="w-56 truncate">{c.method}</span>
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
        </section>
      ))}
    </main>
  );
}
```

- [ ] **Step 3: 加导航入口**

在 `webui/app/etf/[ticker]/page.tsx` 顶部标题区附近加一个链接(用 Next 的 `Link`;若文件已 import 过 `Link` 则复用,否则 `import Link from "next/link";`):

```tsx
<Link
  href="/etf/diagnostics"
  className="rounded-md border border-border/60 px-2.5 py-1 text-xs text-muted-foreground hover:text-primary"
>
  端点诊断
</Link>
```

放在该页现有的操作按钮/标题一行内(与现有布局并列,不新增容器)。

- [ ] **Step 4: 构建 + lint 通过**

Run: `cd webui && npm run build && npm run lint`
Expected: 构建成功、lint 无报错。

- [ ] **Step 5: 手动验证**

启动后端与前端(`./dev.sh`,或分别 `.venv/bin/python -m uvicorn api.main:app --reload --port 8000` 与 `cd webui && npm run dev`),浏览器打开 `http://localhost:3000/etf/diagnostics`,输入一个 ETF 代码(如 `510300.SS`)点「测试」:
- 骨架/逐格回填:格子随 SSE 到达逐个出现并显示状态色。
- 点开某格能看到原始返回全文或错误详情。
- 结束后汇总条显示 ✅/⚠️/🔒/❌ 计数与用时。
- 分析进行中也能跑该页(只读、不被单跑锁阻断)。

- [ ] **Step 6: 提交**

```bash
git add webui/app/etf/diagnostics/page.tsx webui/app/etf/[ticker]/page.tsx
git commit -m "feat(webui): add ETF endpoint diagnostics page"
```

---

### Task 6: 收尾 — 全量 lint/测试 + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 全量 lint**

Run: `.venv/bin/ruff check .`
Expected: 无错误。

- [ ] **Step 2: 全量测试(排除 integration)**

Run: `.venv/bin/python -m pytest -m "not integration" -q`
Expected: 全绿(在 main 基线 0 failed 之上,新增测试通过)。

- [ ] **Step 3: 更新 CHANGELOG**

在 `CHANGELOG.md` 的 `## [Unreleased]` → `### Added` 下追加:

```markdown
- ETF 数据端点诊断页:给定 ETF 代码逐格测试 `VENDOR_METHODS` 数据源矩阵,SSE 流式回填四态状态(成功/无数据·输入不对/无权限/不可用)与原始返回内容(`/etf/diagnostics`,`GET /api/diagnostics/etf/{code}`)。
```

(若无 `## [Unreleased]` 段则按 Keep a Changelog 格式新建。)

- [ ] **Step 4: 提交**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for ETF endpoint diagnostics"
```

---

## Self-Review 记录

- **Spec 覆盖**:第 2 节分类→Task 1;第 3 节后端模块(CellResult/METHOD_PROBES/probe_cell/iter_probes)→Task 2;第 4 节 SSE 协议+路由→Task 3;第 5 节前端→Task 4/5;第 6 节测试→贯穿各 Task + Task 6;第 7 节 YAGNI(不并发/不入库/不改 route_to_vendor)已在实现约束中遵守。
- **偏离 spec 处**:CellResult 用 `group`(3 UI 分区)取代 `category`(`get_category_for_method`)——已在 Task 2 说明理由(同一类别方法分属不同 UI 组)。`get_etf_intraday` 签名已从源码确认为 `(symbol, trade_date, freq="5min")`,探测参数 `(code, ref_date, "5min")`,不再是 spec 里的待定项。
- **类型一致性**:`probe_cell`/`iter_probes`/`count_probes` 签名跨 Task 2/3 一致;前端 `DiagnosticCell.group/status/elapsed_ms/raw/error_type` 与后端 `asdict(CellResult)` 字段一一对应;`subscribeEtfDiagnostics` 事件名 `start/cell/done/error` 与路由 `yield` 的 event 名一致。
