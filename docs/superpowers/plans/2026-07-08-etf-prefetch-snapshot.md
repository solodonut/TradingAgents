# ETF 预取快照 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每个标的分析开始前预取四类数据(新闻/分时/日线K线+指标/基本面)落库到 webui.db,分析时把新闻+行情快照 push 进分析师上下文、其余走 DB-backed 读取,并新增按日期查看快照的独立详情页。新闻按标的类型确定性分流(ETF→`get_etf_news`,股票→`get_news`),输入代码即标注类型。

**Architecture:** 方案 A —— 预取步骤内嵌在 `real_graph_factory`(构建 init_state 处),快照存 webui.db 新表 `etf_snapshots`(键 `ticker+trade_date+category`)。三个新结构化取数函数供图表用,新闻复用现有 `get_etf_news` 字符串。runner 通过 `init_state["prefetched"]` 把摘要 push 给新闻/市场分析师。详情页两个纯读 API + 手绘 SVG 图表(无图表库依赖)。

**Tech Stack:** Python 3.10+ / FastAPI / SQLite(`api/store.py`)/ tushare SDK(`stk_mins`、`fund_daily`、`fund_basic`)/ LangGraph / Next.js 16 + React 19 + react-markdown。

## Global Constraints

- Python 命令一律用 `.venv/bin/python`(不要裸 `python3`/`pytest`/`uvicorn`),避免 NumPy 1.x/2.x 冲突。
- 收尾验证:`.venv/bin/ruff check .` + `.venv/bin/python -m pytest -m "not integration"`;无 CI 兜底。
- dataflows 取数函数**绝不 raise 给上层**:无数据返回 `NO_DATA_AVAILABLE: ...` sentinel 或抛 `NoMarketDataError`(由 `route_to_vendor` 兜住)。预取模块必须永不抛异常。
- 提交规范:Conventional Commits(`feat(scope):`/`test(scope):`),同步维护 `CHANGELOG.md`(Keep a Changelog)。**只有用户明确要求时才 push**;本计划每个任务的 commit 是本地提交。
- 动 `webui/` 前先读 `webui/node_modules/next/dist/docs/` 与 `webui/AGENTS.md`(Next.js 16 破坏性差异)。
- 前端**不新增依赖**;图表用内联 SVG,文本用现有 `react-markdown`(见 `components/MarkdownContent.tsx`)。
- 数据表示取舍(规划决策,已在设计基础上细化):`news` 存 `get_etf_news` 的 markdown 字符串按文本渲染;`intraday`/`daily_kline`/`fundamentals` 用新增结构化函数,分别渲染 SVG 分时图、SVG 日线图、键值卡片。

---

### Task 1: 结构化分时取数 `get_etf_intraday` + vendor 注册

**Files:**
- Create: `tradingagents/dataflows/tushare_intraday.py`
- Modify: `tradingagents/dataflows/interface.py`(import;`TOOLS_CATEGORIES["etf_data"]["tools"]` 追加;`VENDOR_METHODS` 追加)
- Modify: `tradingagents/default_config.py`(`tool_vendors` 追加 `get_etf_intraday`;新增预取配置项)
- Test: `tests/test_etf_intraday.py`

**Interfaces:**
- Produces: `get_etf_intraday(symbol: str, trade_date: str, freq: str = "5min") -> dict`。成功返回 `{"trade_date": str, "freq": str, "points": [{"t": "HH:MM", "price": float, "vol": float}, ...]}`(points 按时间升序);无数据抛 `NoMarketDataError`。

- [ ] **Step 1: 先用 App 的真实 token 手动探活(spec 风险项)**

Run:
```bash
cd "/Users/joseph/Home/Studio/Vibe Code Studio/TradingAgents" && .venv/bin/python -c "
from tradingagents.dataflows.tushare_utils import get_tushare_client
df = get_tushare_client().stk_mins(ts_code='510300.SH', freq='5min', start_date='2026-07-07 09:30:00', end_date='2026-07-07 15:00:00')
print('rows=', len(df)); print(df.head())
"
```
Expected: 打印非空行数与 OHLCV 列。若报权限错(积分不足)→ 记录下来,后续 prefetch 会把该类标 `missing`;本任务的单元测试用 mock,不受影响,可继续。

- [ ] **Step 2: 写失败测试**

```python
# tests/test_etf_intraday.py
import pandas as pd
import pytest

from tradingagents.dataflows import tushare_intraday
from tradingagents.dataflows.errors import NoMarketDataError


def _fake_frame():
    return pd.DataFrame(
        {
            "ts_code": ["510300.SH", "510300.SH"],
            "trade_time": ["2026-07-07 09:35:00", "2026-07-07 09:30:00"],
            "close": [4.859, 4.856],
            "vol": [25748316.0, 4182100.0],
        }
    )


def test_get_etf_intraday_returns_sorted_points(monkeypatch):
    monkeypatch.setattr(
        tushare_intraday, "_fetch_mins", lambda ts_code, trade_date, freq: _fake_frame()
    )
    out = tushare_intraday.get_etf_intraday("510300.SS", "2026-07-07", freq="5min")
    assert out["trade_date"] == "2026-07-07"
    assert out["freq"] == "5min"
    assert [p["t"] for p in out["points"]] == ["09:30", "09:35"]  # 升序
    assert out["points"][0]["price"] == 4.856


def test_get_etf_intraday_empty_raises(monkeypatch):
    monkeypatch.setattr(
        tushare_intraday, "_fetch_mins", lambda ts_code, trade_date, freq: pd.DataFrame()
    )
    with pytest.raises(NoMarketDataError):
        tushare_intraday.get_etf_intraday("510300.SS", "2026-07-07")
```

- [ ] **Step 3: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_etf_intraday.py -v`
Expected: FAIL(`ModuleNotFoundError: tushare_intraday` 或 `AttributeError`)。

- [ ] **Step 4: 实现 `tushare_intraday.py`**

```python
"""Tushare Pro intraday minute bars for mainland ETFs (stk_mins covers ETF codes)."""

from __future__ import annotations

import pandas as pd

from .errors import NoMarketDataError
from .tushare_utils import (
    cached_call,
    call_tushare,
    display_symbol,
    get_tushare_client,
    to_ts_code,
)

_INTRADAY_TTL_SECONDS = 6 * 3600


def _fetch_mins(ts_code: str, trade_date: str, freq: str) -> pd.DataFrame:
    start = f"{trade_date} 09:00:00"
    end = f"{trade_date} 15:30:00"
    cache_key = f"stk_mins/{ts_code}/{trade_date}/{freq}"

    def _fetch():
        client = get_tushare_client()
        return call_tushare(
            lambda: client.stk_mins(
                ts_code=ts_code, freq=freq, start_date=start, end_date=end
            )
        )

    return cached_call(cache_key, _INTRADAY_TTL_SECONDS, _fetch)


def get_etf_intraday(symbol: str, trade_date: str, freq: str = "5min") -> dict:
    ts_code = to_ts_code(symbol)
    raw = _fetch_mins(ts_code, trade_date, freq)
    if raw is None or raw.empty or "trade_time" not in raw.columns:
        raise NoMarketDataError(symbol, ts_code, "no intraday minute data")

    df = raw.sort_values("trade_time")
    points = [
        {
            "t": str(row["trade_time"])[11:16],
            "price": float(row["close"]),
            "vol": float(row.get("vol", 0) or 0),
        }
        for _, row in df.iterrows()
    ]
    if not points:
        raise NoMarketDataError(symbol, display_symbol(symbol), "empty intraday points")
    return {"trade_date": trade_date, "freq": freq, "points": points}
```

- [ ] **Step 5: 注册进 interface.py**

在 `tradingagents/dataflows/interface.py` 顶部 import 区加:
```python
from .tushare_intraday import get_etf_intraday as get_tushare_etf_intraday
```
在 `TOOLS_CATEGORIES["etf_data"]["tools"]` 列表(约 line 131)追加 `"get_etf_intraday"`:
```python
    "etf_data": {
        "description": "ETF-specific data: discount/premium, IOPV, scale, holdings",
        "tools": [
            "get_etf_profile",
            "get_etf_intraday",
        ]
    }
```
在 `VENDOR_METHODS`(约 line 224 的 `get_etf_profile` 后)追加:
```python
    "get_etf_intraday": {
        "tushare": get_tushare_etf_intraday,
    },
```

- [ ] **Step 6: default_config 追加 tool_vendors 与预取配置**

在 `tradingagents/default_config.py` 的 `tool_vendors`(约 line 167)追加:
```python
        "get_etf_intraday": "tushare",
```
在同文件顶层 config dict 追加预取配置(供 Task 3 使用):
```python
    # ETF prefetch snapshot
    "prefetch_retries": 3,            # 每类可恢复错误的重试次数
    "prefetch_backoff_base": 1.0,     # 退避基数(秒),第 n 次退避 = base * 2**(n-1)
    "prefetch_daily_lookback": 60,    # 详情页日线K线回看天数
```

- [ ] **Step 7: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_etf_intraday.py -v`
Expected: PASS(2 passed)。

- [ ] **Step 8: 提交**

```bash
git add tradingagents/dataflows/tushare_intraday.py tradingagents/dataflows/interface.py tradingagents/default_config.py tests/test_etf_intraday.py
git commit -m "feat(dataflows): add structured ETF intraday fetch via tushare stk_mins"
```

---

### Task 2: 结构化日线 K 线取数 `get_etf_daily_kline`

**Files:**
- Modify: `tradingagents/dataflows/tushare_intraday.py`(同模块追加,避免碎文件)
- Test: `tests/test_etf_intraday.py`(追加)

**Interfaces:**
- Consumes: `tushare_utils`(client、`to_ts_code`、`is_fund_symbol`)。
- Produces: `get_etf_daily_kline(symbol: str, trade_date: str, lookback: int = 60) -> dict`。返回 `{"kline": [{"date": "YYYY-MM-DD", "o": float, "h": float, "l": float, "c": float, "vol": float}, ...]}`(按日期升序,最多 lookback 条,截止到 trade_date);无数据抛 `NoMarketDataError`。

- [ ] **Step 1: 写失败测试(追加到 tests/test_etf_intraday.py)**

```python
def _fake_daily():
    return pd.DataFrame(
        {
            "trade_date": ["20260707", "20260704"],
            "open": [4.86, 4.80],
            "high": [4.88, 4.85],
            "low": [4.85, 4.79],
            "close": [4.826, 4.83],
            "vol": [100.0, 90.0],
        }
    )


def test_get_etf_daily_kline_sorted_ascending(monkeypatch):
    monkeypatch.setattr(
        tushare_intraday, "_fetch_daily_raw", lambda ts_code, start, end: _fake_daily()
    )
    out = tushare_intraday.get_etf_daily_kline("510300.SS", "2026-07-07", lookback=60)
    dates = [k["date"] for k in out["kline"]]
    assert dates == ["2026-07-04", "2026-07-07"]
    assert out["kline"][-1]["c"] == 4.826
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_etf_intraday.py::test_get_etf_daily_kline_sorted_ascending -v`
Expected: FAIL(`AttributeError: get_etf_daily_kline`)。

- [ ] **Step 3: 实现(追加到 tushare_intraday.py)**

```python
from datetime import datetime, timedelta

from .tushare_utils import is_fund_symbol

_DAILY_TTL_SECONDS = 6 * 3600


def _fetch_daily_raw(ts_code: str, start: str, end: str) -> pd.DataFrame:
    endpoint_name = "fund_daily" if is_fund_symbol(ts_code) else "daily"
    cache_key = f"kline/{endpoint_name}/{ts_code}/{start}/{end}"

    def _fetch():
        endpoint = getattr(get_tushare_client(), endpoint_name)
        return call_tushare(lambda: endpoint(ts_code=ts_code, start_date=start, end_date=end))

    return cached_call(cache_key, _DAILY_TTL_SECONDS, _fetch)


def get_etf_daily_kline(symbol: str, trade_date: str, lookback: int = 60) -> dict:
    ts_code = to_ts_code(symbol)
    end = trade_date.replace("-", "")
    start_dt = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=lookback * 2 + 10)
    start = start_dt.strftime("%Y%m%d")
    raw = _fetch_daily_raw(ts_code, start, end)
    if raw is None or raw.empty or "trade_date" not in raw.columns:
        raise NoMarketDataError(symbol, ts_code, "no daily kline data")

    df = raw.sort_values("trade_date").tail(lookback)
    kline = [
        {
            "date": f"{str(r['trade_date'])[:4]}-{str(r['trade_date'])[4:6]}-{str(r['trade_date'])[6:8]}",
            "o": float(r["open"]),
            "h": float(r["high"]),
            "l": float(r["low"]),
            "c": float(r["close"]),
            "vol": float(r.get("vol", 0) or 0),
        }
        for _, r in df.iterrows()
    ]
    if not kline:
        raise NoMarketDataError(symbol, ts_code, "empty daily kline")
    return {"kline": kline}
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_etf_intraday.py -v`
Expected: PASS(3 passed)。

- [ ] **Step 5: 提交**

```bash
git add tradingagents/dataflows/tushare_intraday.py tests/test_etf_intraday.py
git commit -m "feat(dataflows): add structured ETF daily kline fetch"
```

---

### Task 3: 结构化基本面键值 `get_etf_fundamentals_kv`

**Files:**
- Modify: `tradingagents/dataflows/tushare_intraday.py`(同模块追加)
- Test: `tests/test_etf_intraday.py`(追加)

**Interfaces:**
- Produces: `get_etf_fundamentals_kv(symbol: str, trade_date: str) -> dict`。返回 `{"items": [{"label": str, "value": str}, ...]}`(如 基金简称/上市日/最新净值/份额);拿不到任何字段抛 `NoMarketDataError`。

- [ ] **Step 1: 写失败测试(追加)**

```python
def test_get_etf_fundamentals_kv_builds_items(monkeypatch):
    monkeypatch.setattr(
        tushare_intraday,
        "_fetch_fund_basic_row",
        lambda ts_code: {"name": "沪深300ETF", "list_date": "20120528"},
    )
    monkeypatch.setattr(
        tushare_intraday,
        "_fetch_fund_nav_row",
        lambda ts_code, trade_date: {"unit_nav": 4.82, "fund_share": 1234.5},
    )
    out = tushare_intraday.get_etf_fundamentals_kv("510300.SS", "2026-07-07")
    labels = {it["label"] for it in out["items"]}
    assert "基金简称" in labels and "最新净值" in labels


def test_get_etf_fundamentals_kv_all_missing_raises(monkeypatch):
    monkeypatch.setattr(tushare_intraday, "_fetch_fund_basic_row", lambda ts_code: {})
    monkeypatch.setattr(
        tushare_intraday, "_fetch_fund_nav_row", lambda ts_code, trade_date: {}
    )
    with pytest.raises(NoMarketDataError):
        tushare_intraday.get_etf_fundamentals_kv("510300.SS", "2026-07-07")
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_etf_intraday.py::test_get_etf_fundamentals_kv_builds_items -v`
Expected: FAIL(`AttributeError`)。

- [ ] **Step 3: 实现(追加到 tushare_intraday.py)**

```python
_FUND_TTL_SECONDS = 24 * 3600


def _fetch_fund_basic_row(ts_code: str) -> dict:
    def _fetch():
        df = call_tushare(lambda: get_tushare_client().fund_basic(ts_code=ts_code))
        return df.iloc[0].to_dict() if df is not None and not df.empty else {}

    return cached_call(f"fund_basic_kv/{ts_code}", _FUND_TTL_SECONDS, _fetch)


def _fetch_fund_nav_row(ts_code: str, trade_date: str) -> dict:
    end = trade_date.replace("-", "")

    def _fetch():
        df = call_tushare(
            lambda: get_tushare_client().fund_nav(ts_code=ts_code, end_date=end)
        )
        return df.iloc[0].to_dict() if df is not None and not df.empty else {}

    return cached_call(f"fund_nav_kv/{ts_code}/{end}", _FUND_TTL_SECONDS, _fetch)


def get_etf_fundamentals_kv(symbol: str, trade_date: str) -> dict:
    ts_code = to_ts_code(symbol)
    basic = _fetch_fund_basic_row(ts_code) or {}
    nav = _fetch_fund_nav_row(ts_code, trade_date) or {}

    candidates = [
        ("基金简称", basic.get("name")),
        ("上市日期", basic.get("list_date")),
        ("管理人", basic.get("management")),
        ("最新净值", nav.get("unit_nav") or nav.get("accum_nav")),
        ("份额(万)", nav.get("fund_share")),
    ]
    items = [
        {"label": label, "value": str(value)}
        for label, value in candidates
        if value not in (None, "", "nan")
    ]
    if not items:
        raise NoMarketDataError(symbol, ts_code, "no fundamentals fields")
    return {"items": items}
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_etf_intraday.py -v`
Expected: PASS(5 passed)。

- [ ] **Step 5: 提交**

```bash
git add tradingagents/dataflows/tushare_intraday.py tests/test_etf_intraday.py
git commit -m "feat(dataflows): add structured ETF fundamentals key-values"
```

---

### Task 4: `etf_snapshots` 表 + Store 读写方法

**Files:**
- Modify: `api/store.py`(`_SCHEMA` 追加建表;新增 3 个方法)
- Test: `tests/webui/test_store.py`(追加)

**Interfaces:**
- Produces(`Store` 实例方法):
  - `upsert_snapshot(self, ticker: str, trade_date: str, category: str, status: str, payload: dict) -> None`
  - `get_snapshot(self, ticker: str, trade_date: str) -> dict[str, dict]`(返回 `{category: {"status": str, "payload": dict, "fetched_at": str}}`,无则 `{}`)
  - `list_snapshot_dates(self, ticker: str) -> list[str]`(DISTINCT trade_date,降序)

- [ ] **Step 1: 写失败测试(追加到 tests/webui/test_store.py)**

```python
def test_snapshot_upsert_and_get(tmp_path):
    store = Store(tmp_path / "s.db")
    store.upsert_snapshot("510300.SS", "2026-07-07", "news", "ok", {"text": "hi"})
    store.upsert_snapshot("510300.SS", "2026-07-07", "intraday", "missing", {})
    snap = store.get_snapshot("510300.SS", "2026-07-07")
    assert snap["news"]["status"] == "ok"
    assert snap["news"]["payload"] == {"text": "hi"}
    assert snap["intraday"]["status"] == "missing"


def test_snapshot_upsert_overwrites_same_key(tmp_path):
    store = Store(tmp_path / "s.db")
    store.upsert_snapshot("510300.SS", "2026-07-07", "news", "ok", {"text": "v1"})
    store.upsert_snapshot("510300.SS", "2026-07-07", "news", "ok", {"text": "v2"})
    snap = store.get_snapshot("510300.SS", "2026-07-07")
    assert snap["news"]["payload"] == {"text": "v2"}


def test_list_snapshot_dates_desc(tmp_path):
    store = Store(tmp_path / "s.db")
    store.upsert_snapshot("510300.SS", "2026-07-04", "news", "ok", {})
    store.upsert_snapshot("510300.SS", "2026-07-07", "news", "ok", {})
    assert store.list_snapshot_dates("510300.SS") == ["2026-07-07", "2026-07-04"]
    assert store.list_snapshot_dates("000001.SS") == []
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_store.py::test_snapshot_upsert_and_get -v`
Expected: FAIL(`AttributeError: upsert_snapshot`)。

- [ ] **Step 3: 建表 —— 在 `api/store.py` 的 `_SCHEMA` 末尾追加**

```sql
CREATE TABLE IF NOT EXISTS etf_snapshots (
    ticker       TEXT NOT NULL,
    trade_date   TEXT NOT NULL,
    category     TEXT NOT NULL,
    status       TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (ticker, trade_date, category)
);
```

- [ ] **Step 4: 实现方法 —— 在 `Store` 类内追加(仿现有 `with self._lock, self._connect()` 风格)**

```python
    def upsert_snapshot(
        self, ticker: str, trade_date: str, category: str, status: str, payload: dict
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO etf_snapshots "
                "(ticker, trade_date, category, status, payload_json, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ticker, trade_date, category, status, _dumps(payload), _now()),
            )

    def get_snapshot(self, ticker: str, trade_date: str) -> dict[str, dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT category, status, payload_json, fetched_at FROM etf_snapshots "
                "WHERE ticker=? AND trade_date=?",
                (ticker, trade_date),
            ).fetchall()
        return {
            r["category"]: {
                "status": r["status"],
                "payload": json.loads(r["payload_json"]),
                "fetched_at": r["fetched_at"],
            }
            for r in rows
        }

    def list_snapshot_dates(self, ticker: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT trade_date FROM etf_snapshots WHERE ticker=? "
                "ORDER BY trade_date DESC",
                (ticker,),
            ).fetchall()
        return [r["trade_date"] for r in rows]
```

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_store.py -v`
Expected: PASS(含新增 3 个)。

- [ ] **Step 6: 提交**

```bash
git add api/store.py tests/webui/test_store.py
git commit -m "feat(store): add etf_snapshots table and read/write methods"
```

---

### Task 5: 预取模块 `prefetch_snapshot` + 重试/退避/missing + `SnapshotSummary`

**Files:**
- Create: `tradingagents/dataflows/prefetch.py`
- Test: `tests/test_prefetch.py`

**Interfaces:**
- Consumes: `route_to_vendor`(`get_etf_news`、`get_news`、`get_indicators`);`tushare_utils.resolve_symbol_type`(本任务 Step 0 新增);`tushare_intraday.get_etf_intraday/get_etf_daily_kline/get_etf_fundamentals_kv`;`Store.upsert_snapshot`(Task 4);config(Task 1 的 `prefetch_retries`/`prefetch_backoff_base`/`prefetch_daily_lookback`)。
- Produces(本任务顺带新增,供 Task 12 复用): `resolve_symbol_type(symbol: str) -> str`,返回 `"etf"`(`is_fund_symbol` 为真)或 `"stock"`。
- Produces:
  - `@dataclass CategoryResult(category: str, status: str, payload: dict)`
  - `@dataclass SnapshotSummary(ticker, trade_date, results: list[CategoryResult])`,方法 `for_context() -> dict`
  - `prefetch_snapshot(ticker: str, trade_date: str, store, *, config: dict | None = None, sleep=time.sleep) -> SnapshotSummary`

- [ ] **Step 0: 新增类型原语 `resolve_symbol_type`(TDD)**

先在 `tests/test_tushare_utils.py`(无则新建)追加:
```python
from tradingagents.dataflows.tushare_utils import resolve_symbol_type


def test_resolve_symbol_type_etf_vs_stock():
    assert resolve_symbol_type("510300.SS") == "etf"
    assert resolve_symbol_type("159915.SZ") == "etf"
    assert resolve_symbol_type("600519.SS") == "stock"
    assert resolve_symbol_type("000001.SZ") == "stock"
```
运行确认失败:`.venv/bin/python -m pytest tests/test_tushare_utils.py::test_resolve_symbol_type_etf_vs_stock -v`(`AttributeError`)。

在 `tradingagents/dataflows/tushare_utils.py` 的 `is_fund_symbol` 之后追加:
```python
def resolve_symbol_type(symbol: str) -> str:
    """Return "etf" for a recognized mainland fund/ETF code, else "stock"."""
    return "etf" if is_fund_symbol(symbol) else "stock"
```
运行确认通过。此原语同时供本任务 `_fetch_news` 与 Task 12 的 ticker 路由复用。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_prefetch.py
from tradingagents.dataflows import prefetch


class FakeStore:
    def __init__(self):
        self.rows = {}

    def upsert_snapshot(self, ticker, trade_date, category, status, payload):
        self.rows[category] = (status, payload)


def _cfg():
    return {"prefetch_retries": 2, "prefetch_backoff_base": 0.0, "prefetch_daily_lookback": 60}


def test_prefetch_all_ok(monkeypatch):
    monkeypatch.setattr(prefetch, "_fetch_news", lambda t, d: {"text": "news"})
    monkeypatch.setattr(prefetch, "_fetch_intraday", lambda t, d: {"points": [1]})
    monkeypatch.setattr(prefetch, "_fetch_indicators", lambda t, d, lb: {"kline": [1]})
    monkeypatch.setattr(prefetch, "_fetch_fundamentals", lambda t, d: {"items": [1]})
    store = FakeStore()
    summary = prefetch.prefetch_snapshot("510300.SS", "2026-07-07", store, config=_cfg(), sleep=lambda s: None)
    assert {r.category: r.status for r in summary.results} == {
        "news": "ok", "intraday": "ok", "indicators": "ok", "fundamentals": "ok"
    }
    assert store.rows["news"][0] == "ok"


def test_prefetch_marks_missing_on_persistent_error(monkeypatch):
    calls = {"n": 0}

    def boom(t, d):
        calls["n"] += 1
        raise TimeoutError("rate limited")

    monkeypatch.setattr(prefetch, "_fetch_news", boom)
    monkeypatch.setattr(prefetch, "_fetch_intraday", lambda t, d: {"points": [1]})
    monkeypatch.setattr(prefetch, "_fetch_indicators", lambda t, d, lb: {"kline": [1]})
    monkeypatch.setattr(prefetch, "_fetch_fundamentals", lambda t, d: {"items": [1]})
    store = FakeStore()
    summary = prefetch.prefetch_snapshot("510300.SS", "2026-07-07", store, config=_cfg(), sleep=lambda s: None)
    news = next(r for r in summary.results if r.category == "news")
    assert news.status == "missing"
    assert calls["n"] == 2  # retries 用尽(prefetch_retries=2)
    assert "news" in summary.for_context()["missing"]


def test_prefetch_no_data_not_retried(monkeypatch):
    calls = {"n": 0}

    def nodata(t, d):
        calls["n"] += 1
        return "NO_DATA_AVAILABLE: none"

    monkeypatch.setattr(prefetch, "_fetch_news", nodata)
    monkeypatch.setattr(prefetch, "_fetch_intraday", lambda t, d: {"points": [1]})
    monkeypatch.setattr(prefetch, "_fetch_indicators", lambda t, d, lb: {"kline": [1]})
    monkeypatch.setattr(prefetch, "_fetch_fundamentals", lambda t, d: {"items": [1]})
    store = FakeStore()
    summary = prefetch.prefetch_snapshot("510300.SS", "2026-07-07", store, config=_cfg(), sleep=lambda s: None)
    news = next(r for r in summary.results if r.category == "news")
    assert news.status == "missing"
    assert calls["n"] == 1  # NO_DATA 不重试


def test_prefetch_never_raises(monkeypatch):
    monkeypatch.setattr(prefetch, "_fetch_news", lambda t, d: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(prefetch, "_fetch_intraday", lambda t, d: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(prefetch, "_fetch_indicators", lambda t, d, lb: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(prefetch, "_fetch_fundamentals", lambda t, d: (_ for _ in ()).throw(RuntimeError("x")))
    store = FakeStore()
    summary = prefetch.prefetch_snapshot("510300.SS", "2026-07-07", store, config=_cfg(), sleep=lambda s: None)
    assert all(r.status == "missing" for r in summary.results)


def test_fetch_news_routes_by_type(monkeypatch):
    seen = []

    def fake_route(method, *a, **k):
        seen.append(method)
        return "news body"

    monkeypatch.setattr(prefetch, "route_to_vendor", fake_route)
    prefetch._fetch_news("510300.SS", "2026-07-07")  # ETF → get_etf_news
    prefetch._fetch_news("600519.SS", "2026-07-07")  # 股票 → get_news
    assert seen == ["get_etf_news", "get_news"]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_prefetch.py -v`
Expected: FAIL(`ModuleNotFoundError: prefetch`)。

- [ ] **Step 3: 实现 `prefetch.py`**

```python
"""Pre-fetch four ETF data categories and persist per-date snapshots.

Runs once per ETF right before its analysis. Never raises: any category that
fails after retries is marked ``missing`` so analysis proceeds with an explicit
"unavailable" marker rather than fabricated values.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

from .config import get_config
from .errors import NoMarketDataError
from .interface import route_to_vendor
from .tushare_intraday import (
    get_etf_daily_kline,
    get_etf_fundamentals_kv,
    get_etf_intraday,
)
from .tushare_utils import resolve_symbol_type

_CATEGORIES = ("news", "intraday", "indicators", "fundamentals")
_NODATA_PREFIXES = ("NO_DATA_AVAILABLE", "DATA_SOURCE_")


@dataclass
class CategoryResult:
    category: str
    status: str  # ok | partial | missing
    payload: dict


@dataclass
class SnapshotSummary:
    ticker: str
    trade_date: str
    results: list[CategoryResult]

    def _by(self, category: str) -> CategoryResult | None:
        return next((r for r in self.results if r.category == category), None)

    def for_context(self) -> dict:
        """Compact block pushed into analyst context (news text + quote + missing)."""
        missing = [r.category for r in self.results if r.status == "missing"]
        news = self._by("news")
        intraday = self._by("intraday")
        quote = None
        if intraday and intraday.status != "missing":
            pts = intraday.payload.get("points") or []
            if pts:
                quote = {"last_price": pts[-1]["price"], "trade_date": self.trade_date}
        return {
            "ticker": self.ticker,
            "trade_date": self.trade_date,
            "news_text": (news.payload.get("text") if news and news.status != "missing" else None),
            "quote": quote,
            "missing": missing,
        }


def _is_nodata(result) -> bool:
    return isinstance(result, str) and result.startswith(_NODATA_PREFIXES)


# --- per-category fetchers (patched in tests) -----------------------------

def _fetch_news(ticker: str, trade_date: str):
    end = datetime.strptime(trade_date, "%Y-%m-%d")
    start = (end - relativedelta(days=7)).strftime("%Y-%m-%d")
    # 类型感知分流:ETF→get_etf_news(基金+主题+持仓聚合),股票→get_news(个股)。
    method = "get_etf_news" if resolve_symbol_type(ticker) == "etf" else "get_news"
    result = route_to_vendor(method, ticker, start, trade_date)
    if _is_nodata(result):
        return result
    return {"text": result}


def _fetch_intraday(ticker: str, trade_date: str):
    return get_etf_intraday(ticker, trade_date)


def _fetch_indicators(ticker: str, trade_date: str, lookback: int):
    kline = get_etf_daily_kline(ticker, trade_date, lookback=lookback)
    end = datetime.strptime(trade_date, "%Y-%m-%d")
    start = (end - relativedelta(days=lookback)).strftime("%Y-%m-%d")
    text = route_to_vendor("get_indicators", ticker, start, trade_date)
    return {"kline": kline["kline"], "indicator_text": None if _is_nodata(text) else text}


def _fetch_fundamentals(ticker: str, trade_date: str):
    return get_etf_fundamentals_kv(ticker, trade_date)


def _run_with_retry(fn, retries: int, backoff_base: float, sleep) -> tuple[str, dict]:
    """Return (status, payload). Never raises. NO_DATA is not retried."""
    attempt = 0
    while True:
        attempt += 1
        try:
            result = fn()
        except NoMarketDataError:
            return "missing", {}
        except Exception:  # noqa: BLE001 - transient; retry then give up
            if attempt >= retries:
                return "missing", {}
            if backoff_base:
                sleep(backoff_base * (2 ** (attempt - 1)))
            continue
        if _is_nodata(result):
            return "missing", {}
        if not isinstance(result, dict) or not result:
            return "missing", {}
        return "ok", result


def prefetch_snapshot(ticker, trade_date, store, *, config=None, sleep=time.sleep) -> SnapshotSummary:
    config = config or get_config()
    retries = int(config.get("prefetch_retries", 3))
    backoff = float(config.get("prefetch_backoff_base", 1.0))
    lookback = int(config.get("prefetch_daily_lookback", 60))

    fetchers = {
        "news": lambda: _fetch_news(ticker, trade_date),
        "intraday": lambda: _fetch_intraday(ticker, trade_date),
        "indicators": lambda: _fetch_indicators(ticker, trade_date, lookback),
        "fundamentals": lambda: _fetch_fundamentals(ticker, trade_date),
    }

    results: list[CategoryResult] = []
    for category in _CATEGORIES:
        status, payload = _run_with_retry(fetchers[category], retries, backoff, sleep)
        store.upsert_snapshot(ticker, trade_date, category, status, payload)
        results.append(CategoryResult(category=category, status=status, payload=payload))

    return SnapshotSummary(ticker=ticker, trade_date=trade_date, results=results)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_prefetch.py tests/test_tushare_utils.py -v`
Expected: PASS(prefetch 5 passed + resolve_symbol_type 1 passed)。

- [ ] **Step 5: 提交**

```bash
git add tradingagents/dataflows/prefetch.py tradingagents/dataflows/tushare_utils.py tests/test_prefetch.py tests/test_tushare_utils.py
git commit -m "feat(dataflows): add prefetch_snapshot with type-aware news routing, retry/backoff, missing marking"
```

---

### Task 6: state 增加 `prefetched` 字段 + `real_graph_factory` 集成预取

**Files:**
- Modify: `tradingagents/agents/utils/agent_states.py`(`AgentState` 加字段)
- Modify: `tradingagents/graph/propagation.py`(`create_initial_state` 初始化 `prefetched=None`)
- Modify: `api/main.py`(`real_graph_factory` 调 `prefetch_snapshot` 并注入)
- Test: `tests/webui/test_graph_factory.py`(追加)

**Interfaces:**
- Consumes: `prefetch_snapshot`(Task 5);`get_store`(api/main)。
- Produces: `init_state["prefetched"]`(`SnapshotSummary.for_context()` 的 dict,或 `None`)。

- [ ] **Step 1: 写失败测试(追加到 tests/webui/test_graph_factory.py)**

```python
def test_real_graph_factory_injects_prefetched(monkeypatch):
    import api.main as main
    from api.schemas import AnalysisRequest

    captured = {}

    class FakeSummary:
        def for_context(self):
            return {"ticker": "510300.SS", "missing": [], "news_text": "n", "quote": None}

    def fake_prefetch(ticker, trade_date, store, **kw):
        captured["ticker"] = ticker
        return FakeSummary()

    monkeypatch.setattr(main, "prefetch_snapshot", fake_prefetch)
    # 用一个最小假 graph 工厂路径:直接调 real_graph_factory 依赖 TradingAgentsGraph,
    # 这里跳过真实 graph,断言注入逻辑通过 _inject_prefetched 辅助函数完成。
    init_state = {"company_of_interest": "510300.SS"}
    main._inject_prefetched(init_state, "510300.SS", "2026-07-07", store=None)
    assert init_state["prefetched"]["news_text"] == "n"
    assert captured["ticker"] == "510300.SS"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_graph_factory.py::test_real_graph_factory_injects_prefetched -v`
Expected: FAIL(`AttributeError: _inject_prefetched`)。

- [ ] **Step 3: `AgentState` 加字段** —— 在 `tradingagents/agents/utils/agent_states.py` 的 `AgentState` 内(仿邻近 `Annotated` 字段)加:

```python
    prefetched: Annotated[dict | None, "Pre-fetched ETF snapshot summary for context injection"]
```

- [ ] **Step 4: `create_initial_state` 初始化** —— 在 `tradingagents/graph/propagation.py` 返回的 dict 里加一行(在 `"news_report": ""` 附近):

```python
            "prefetched": None,
```

- [ ] **Step 5: `api/main.py` 集成** —— 顶部 import 加:

```python
from tradingagents.dataflows.prefetch import prefetch_snapshot
```

在 `real_graph_factory` 内,`init_state = graph.propagator.create_initial_state(...)` 之后、`return` 之前加:

```python
    _inject_prefetched(init_state, req.ticker, req.trade_date, store=get_store())
```

并在模块内新增辅助函数(TradingAgentsGraph 构造已调用 set_config,dataflows 配置就绪;预取永不抛):

```python
def _inject_prefetched(init_state: dict, ticker: str, trade_date: str, store) -> None:
    try:
        summary = prefetch_snapshot(ticker, trade_date, store)
        init_state["prefetched"] = summary.for_context()
    except Exception:  # noqa: BLE001 - prefetch must never block a run
        logger.exception("prefetch: snapshot failed for %s %s", ticker, trade_date)
        init_state["prefetched"] = None
```

- [ ] **Step 6: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_graph_factory.py -v`
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add tradingagents/agents/utils/agent_states.py tradingagents/graph/propagation.py api/main.py tests/webui/test_graph_factory.py
git commit -m "feat(api): prefetch ETF snapshot in graph factory and inject into state"
```

---

### Task 7: push 投喂 —— 新闻/市场分析师读 `prefetched`

**Files:**
- Create: `tradingagents/agents/utils/prefetch_context.py`(纯函数,拼上下文块)
- Modify: `tradingagents/agents/analysts/news_analyst.py`
- Modify: `tradingagents/agents/analysts/market_analyst.py`
- Test: `tests/test_prefetch_context.py`

**Interfaces:**
- Produces: `build_prefetch_block(prefetched: dict | None, *, want_news: bool, want_quote: bool) -> str`。返回要拼进 system_message 的文本块(无数据/None 返回 `""`;missing 项明确标注不可用)。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_prefetch_context.py
from tradingagents.agents.utils.prefetch_context import build_prefetch_block


def test_block_includes_news_and_quote():
    pf = {"news_text": "重要新闻...", "quote": {"last_price": 4.82, "trade_date": "2026-07-07"}, "missing": []}
    block = build_prefetch_block(pf, want_news=True, want_quote=True)
    assert "重要新闻" in block
    assert "4.82" in block


def test_block_marks_missing():
    pf = {"news_text": None, "quote": None, "missing": ["news", "intraday"]}
    block = build_prefetch_block(pf, want_news=True, want_quote=True)
    assert "暂缺" in block or "unavailable" in block.lower()


def test_block_empty_when_none():
    assert build_prefetch_block(None, want_news=True, want_quote=True) == ""
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_prefetch_context.py -v`
Expected: FAIL(`ModuleNotFoundError`)。

- [ ] **Step 3: 实现 `prefetch_context.py`**

```python
"""Assemble the pre-fetched data block pushed into analyst prompts."""

from __future__ import annotations


def build_prefetch_block(prefetched, *, want_news: bool, want_quote: bool) -> str:
    if not prefetched:
        return ""

    missing = set(prefetched.get("missing") or [])
    lines: list[str] = []

    if want_quote:
        quote = prefetched.get("quote")
        if quote:
            lines.append(
                f"- 当前行情快照(预取):最新价 {quote['last_price']}(交易日 {quote['trade_date']})。"
            )
        elif "intraday" in missing:
            lines.append("- ⚠️ 分时/行情快照本次预取暂缺,不可用——请勿臆测价格。")

    if want_news:
        news_text = prefetched.get("news_text")
        if news_text:
            lines.append("- 预取新闻(直接使用,无需再调用工具):\n" + str(news_text))
        elif "news" in missing:
            lines.append("- ⚠️ 新闻本次预取暂缺,不可用——请如实说明缺失,不要编造。")

    if not lines:
        return ""
    return "\n\n【预取数据(本次分析开始前已抓取)】\n" + "\n".join(lines) + "\n"
```

- [ ] **Step 4: news_analyst 接入** —— 在 `tradingagents/agents/analysts/news_analyst.py`,`import` 处加:

```python
from tradingagents.agents.utils.prefetch_context import build_prefetch_block
```

在 `news_analyst_node` 内,构造完 `system_message` 后(两个分支都覆盖,故加在 `prompt = ChatPromptTemplate...` 之前)追加:

```python
        system_message += build_prefetch_block(
            state.get("prefetched"), want_news=True, want_quote=False
        )
```

- [ ] **Step 5: market_analyst 接入** —— 在 `tradingagents/agents/analysts/market_analyst.py` 同样 import,并在 `system_message` 构造后、`prompt` 组装前追加:

```python
        system_message += build_prefetch_block(
            state.get("prefetched"), want_news=False, want_quote=True
        )
```

- [ ] **Step 6: 运行确认通过 + 冒烟不回归**

Run: `.venv/bin/python -m pytest tests/test_prefetch_context.py tests/test_china_only_data_sources.py -v`
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add tradingagents/agents/utils/prefetch_context.py tradingagents/agents/analysts/news_analyst.py tradingagents/agents/analysts/market_analyst.py tests/test_prefetch_context.py
git commit -m "feat(agents): push prefetched news and quote into analyst context"
```

---

### Task 8: pull 路径 —— `get_etf_news` / `get_news` 工具优先读快照 DB

**Files:**
- Modify: `tradingagents/agents/utils/news_data_tools.py`(`get_etf_news` **和 `get_news`** 各加"先查快照"短路)
- Modify: `tradingagents/dataflows/config.py`(暴露当前 run 的 ticker/date/store —— 见下)
- Test: `tests/test_tushare_etf_news.py`(追加,或新建 `tests/test_etf_news_snapshot_shortcircuit.py`)

**说明:** 工具需知道"当前 ticker/date + store"。最小侵入方案:在 `real_graph_factory` 注入预取时,把 `(ticker, trade_date, store)` 存入 dataflows 的 config 单例(一个 `_prefetch_ctx` 键);工具读取该 ctx,命中则直接返回快照的 `news.text`,否则回落现有在线逻辑。新闻快照与工具无关(存的是文本),故 **`get_etf_news`(ETF 跑法)和 `get_news`(股票跑法)对称短路** —— 谁被调都命中同一份 `news` 快照。

**Interfaces:**
- Consumes: `Store.get_snapshot`(Task 4);config 单例。
- Produces: `set_prefetch_ctx(ticker, trade_date, store)` / `get_prefetch_ctx() -> dict | None`(放 `tradingagents/dataflows/config.py`)。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_etf_news_snapshot_shortcircuit.py
from tradingagents.dataflows import config as dfconfig


class FakeStore:
    def get_snapshot(self, ticker, trade_date):
        return {"news": {"status": "ok", "payload": {"text": "SNAPSHOT NEWS"}, "fetched_at": "t"}}


def test_get_etf_news_uses_snapshot(monkeypatch):
    from tradingagents.agents.utils.news_data_tools import get_etf_news

    dfconfig.set_prefetch_ctx("510300.SS", "2026-07-07", FakeStore())
    try:
        out = get_etf_news.invoke(
            {"symbol": "510300.SS", "start_date": "2026-07-01", "end_date": "2026-07-07"}
        )
        assert "SNAPSHOT NEWS" in out
    finally:
        dfconfig.set_prefetch_ctx(None, None, None)


def test_get_news_uses_snapshot(monkeypatch):
    from tradingagents.agents.utils.news_data_tools import get_news

    dfconfig.set_prefetch_ctx("600519.SS", "2026-07-07", FakeStore())
    try:
        out = get_news.invoke(
            {"ticker": "600519.SS", "start_date": "2026-07-01", "end_date": "2026-07-07"}
        )
        assert "SNAPSHOT NEWS" in out
    finally:
        dfconfig.set_prefetch_ctx(None, None, None)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_etf_news_snapshot_shortcircuit.py -v`
Expected: FAIL(`AttributeError: set_prefetch_ctx`)。

- [ ] **Step 3: config 暴露 prefetch ctx** —— 在 `tradingagents/dataflows/config.py` 追加:

```python
_PREFETCH_CTX: dict | None = None


def set_prefetch_ctx(ticker, trade_date, store) -> None:
    global _PREFETCH_CTX
    _PREFETCH_CTX = None if ticker is None else {
        "ticker": ticker, "trade_date": trade_date, "store": store
    }


def get_prefetch_ctx():
    return _PREFETCH_CTX
```

- [ ] **Step 4: 两个工具对称短路** —— 在 `tradingagents/agents/utils/news_data_tools.py` 模块级(`@tool` 定义之前)加共享辅助:

```python
def _snapshot_news(symbol: str) -> str | None:
    """Return the prefetched news text for the current run's symbol, else None."""
    from tradingagents.dataflows.config import get_prefetch_ctx

    ctx = get_prefetch_ctx()
    if ctx and ctx.get("ticker") == symbol and ctx.get("store") is not None:
        snap = ctx["store"].get_snapshot(symbol, ctx["trade_date"]).get("news")
        if snap and snap["status"] == "ok" and snap["payload"].get("text"):
            return snap["payload"]["text"]
    return None
```

在 `get_etf_news` 函数体最前面加:
```python
    hit = _snapshot_news(symbol)
    if hit is not None:
        return hit
```

在 `get_news` 函数体最前面加(注意入参名是 `ticker`):
```python
    hit = _snapshot_news(ticker)
    if hit is not None:
        return hit
```

(若无匹配快照则继续现有在线逻辑,不改动其余代码。)

- [ ] **Step 5: `real_graph_factory` 设置/清理 ctx** —— 在 `api/main.py` 的 `_inject_prefetched` 成功后设置 ctx:

```python
        from tradingagents.dataflows.config import set_prefetch_ctx
        set_prefetch_ctx(ticker, trade_date, store)
```

并在 `api/runner.py` 的 `run()` `finally` 块中清理(避免污染下个 run),在 `self._q.put(None)` 之前加:

```python
            from tradingagents.dataflows.config import set_prefetch_ctx
            set_prefetch_ctx(None, None, None)
```

- [ ] **Step 6: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_etf_news_snapshot_shortcircuit.py -v`
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add tradingagents/dataflows/config.py tradingagents/agents/utils/news_data_tools.py api/main.py api/runner.py tests/test_etf_news_snapshot_shortcircuit.py
git commit -m "feat(agents): serve get_etf_news and get_news from prefetched snapshot when available"
```

---

### Task 9: 详情页 API —— dates + snapshot(两个纯读路由)

**Files:**
- Create: `api/routes/snapshots.py`
- Modify: `api/main.py`(注册路由)
- Test: `tests/webui/test_routes_snapshots.py`;`tests/webui/test_smoke.py`(追加注册断言)

**Interfaces:**
- Consumes: `get_store`;`Store.list_snapshot_dates`/`get_snapshot`(Task 4)。
- Produces:
  - `GET /api/etf/{ticker}/dates` → `{"ticker": str, "dates": [str, ...]}`
  - `GET /api/etf/{ticker}/snapshot?date=YYYY-MM-DD` → `{"ticker": str, "trade_date": str, "categories": {category: {"status","payload"}}}`

- [ ] **Step 1: 写失败测试**

```python
# tests/webui/test_routes_snapshots.py
def test_etf_dates_and_snapshot(client):
    import api.main as main

    store = main.get_store()
    store.upsert_snapshot("510300.SS", "2026-07-07", "news", "ok", {"text": "hi"})

    r = client.get("/api/etf/510300.SS/dates")
    assert r.status_code == 200
    assert r.json()["dates"] == ["2026-07-07"]

    r2 = client.get("/api/etf/510300.SS/snapshot", params={"date": "2026-07-07"})
    assert r2.status_code == 200
    assert r2.json()["categories"]["news"]["payload"] == {"text": "hi"}


def test_etf_snapshot_empty_date_returns_empty(client):
    r = client.get("/api/etf/000001.SS/snapshot", params={"date": "2026-07-07"})
    assert r.status_code == 200
    assert r.json()["categories"] == {}
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_snapshots.py -v`
Expected: FAIL(404)。

- [ ] **Step 3: 实现 `api/routes/snapshots.py`**

```python
"""ETF snapshot routes: list snapshot dates and read one date's snapshot."""

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/etf", tags=["etf-snapshots"])


@router.get("/{ticker}/dates")
def etf_snapshot_dates(ticker: str, request: Request) -> dict:
    from api.main import get_store

    return {"ticker": ticker, "dates": get_store().list_snapshot_dates(ticker)}


@router.get("/{ticker}/snapshot")
def etf_snapshot(ticker: str, date: str = Query(...), request: Request = None) -> dict:
    from api.main import get_store

    snap = get_store().get_snapshot(ticker, date)
    categories = {
        cat: {"status": v["status"], "payload": v["payload"]} for cat, v in snap.items()
    }
    return {"ticker": ticker, "trade_date": date, "categories": categories}
```

- [ ] **Step 4: 注册路由** —— 在 `api/main.py` 底部(仿 watchlist 注册)加:

```python
from api.routes import snapshots as snapshots_routes  # noqa: E402

app.include_router(snapshots_routes.router)
```

- [ ] **Step 5: 冒烟断言** —— 在 `tests/webui/test_smoke.py` 追加:

```python
@pytest.mark.smoke
def test_snapshot_routes_registered():
    from api.main import app

    client = TestClient(app)
    assert client.get("/api/etf/510300.SS/dates").status_code == 200
```

- [ ] **Step 6: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_snapshots.py tests/webui/test_smoke.py -v`
Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add api/routes/snapshots.py api/main.py tests/webui/test_routes_snapshots.py tests/webui/test_smoke.py
git commit -m "feat(api): add ETF snapshot dates and read routes"
```

---

### Task 10: 前端 API 客户端 + 类型 + SVG 折线纯函数

**Files:**
- Modify: `webui/lib/types.ts`(新增快照类型)
- Modify: `webui/lib/api.ts`(新增两个 fetch 函数)
- Create: `webui/lib/etf-chart.ts` + `webui/lib/etf-chart.test.ts`

**先读:** `webui/AGENTS.md`;`webui/lib/api.ts` 现有 fetch 模式;`webui/lib/startup-cache.ts`(纯函数+测试模式)。

**Interfaces:**
- Produces:
  - types: `EtfSnapshotCategory = { status: "ok"|"partial"|"missing"; payload: any }`;`EtfSnapshot = { ticker: string; trade_date: string; categories: Record<string, EtfSnapshotCategory> }`
  - `getEtfSnapshotDates(ticker: string): Promise<string[]>`
  - `getEtfSnapshot(ticker: string, date: string): Promise<EtfSnapshot>`
  - `buildLinePath(points: {t:string; price:number}[], width:number, height:number, pad:number): string`(返回 SVG `d`)

- [ ] **Step 1: 写失败测试**

```typescript
// webui/lib/etf-chart.test.ts
import { describe, it, expect } from "vitest";
import { buildLinePath } from "./etf-chart";

describe("buildLinePath", () => {
  it("returns empty string for no points", () => {
    expect(buildLinePath([], 100, 40, 2)).toBe("");
  });
  it("maps first point to left and scales within bounds", () => {
    const d = buildLinePath(
      [{ t: "09:30", price: 1 }, { t: "09:35", price: 2 }],
      100, 40, 2,
    );
    expect(d.startsWith("M")).toBe(true);
    expect(d).toContain("L");
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd webui && npx vitest run lib/etf-chart.test.ts`
Expected: FAIL(module not found)。

- [ ] **Step 3: 实现 `webui/lib/etf-chart.ts`**

```typescript
export function buildLinePath(
  points: { t: string; price: number }[],
  width: number,
  height: number,
  pad: number,
): string {
  if (points.length === 0) return "";
  const prices = points.map((p) => p.price);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = max - min || 1;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  const step = points.length > 1 ? innerW / (points.length - 1) : 0;
  return points
    .map((p, i) => {
      const x = pad + step * i;
      const y = pad + innerH - ((p.price - min) / span) * innerH;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}
```

- [ ] **Step 4: 类型 + API 客户端** —— `webui/lib/types.ts` 追加:

```typescript
export type EtfSnapshotCategory = { status: "ok" | "partial" | "missing"; payload: any };
export type EtfSnapshot = {
  ticker: string;
  trade_date: string;
  categories: Record<string, EtfSnapshotCategory>;
};
```

`webui/lib/api.ts` 追加(仿现有 `getWatchlist` 模式,`import type { EtfSnapshot } from "./types"`):

```typescript
export async function getEtfSnapshotDates(ticker: string): Promise<string[]> {
  const r = await fetch(`${BASE}/api/etf/${encodeURIComponent(ticker)}/dates`);
  if (!r.ok) throw new Error("failed to load snapshot dates");
  return (await r.json()).dates as string[];
}

export async function getEtfSnapshot(ticker: string, date: string): Promise<EtfSnapshot> {
  const r = await fetch(
    `${BASE}/api/etf/${encodeURIComponent(ticker)}/snapshot?date=${encodeURIComponent(date)}`,
  );
  if (!r.ok) throw new Error("failed to load snapshot");
  return r.json();
}
```

- [ ] **Step 5: 运行确认通过**

Run: `cd webui && npx vitest run lib/etf-chart.test.ts`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add webui/lib/types.ts webui/lib/api.ts webui/lib/etf-chart.ts webui/lib/etf-chart.test.ts
git commit -m "feat(webui): add ETF snapshot api client and SVG line path helper"
```

---

### Task 11: ETF 详情页 `app/etf/[ticker]/page.tsx`

**Files:**
- Create: `webui/app/etf/[ticker]/page.tsx`

**先读:** `webui/app/logs/[runId]/page.tsx`(client page 模式)、`webui/components/MarkdownContent.tsx`(markdown 渲染)。

**Interfaces:**
- Consumes: `getEtfSnapshotDates`/`getEtfSnapshot`(Task 10);`buildLinePath`(Task 10);`MarkdownContent`。

- [ ] **Step 1: 实现详情页**

```tsx
"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getEtfSnapshot, getEtfSnapshotDates } from "@/lib/api";
import type { EtfSnapshot } from "@/lib/types";
import { buildLinePath } from "@/lib/etf-chart";
import MarkdownContent from "@/components/MarkdownContent";

function MissingNote() {
  return <p className="text-sm text-muted-foreground">本次预取暂缺,不可用。</p>;
}

function IntradayChart({ payload }: { payload: any }) {
  const points = (payload?.points ?? []) as { t: string; price: number }[];
  if (points.length === 0) return <MissingNote />;
  const W = 640, H = 200, PAD = 8;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-48">
      <path d={buildLinePath(points, W, H, PAD)} fill="none" stroke="currentColor" strokeWidth={1.5} />
    </svg>
  );
}

function DailyChart({ payload }: { payload: any }) {
  const kline = (payload?.kline ?? []) as { date: string; c: number }[];
  if (kline.length === 0) return <MissingNote />;
  const pts = kline.map((k) => ({ t: k.date, price: k.c }));
  const W = 640, H = 200, PAD = 8;
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-48">
        <path d={buildLinePath(pts, W, H, PAD)} fill="none" stroke="currentColor" strokeWidth={1.5} />
      </svg>
      {payload?.indicator_text ? <MarkdownContent content={payload.indicator_text} /> : null}
    </>
  );
}

function Fundamentals({ payload }: { payload: any }) {
  const items = (payload?.items ?? []) as { label: string; value: string }[];
  if (items.length === 0) return <MissingNote />;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {items.map((it) => (
        <div key={it.label} className="rounded-lg border p-3">
          <div className="text-xs text-muted-foreground">{it.label}</div>
          <div className="text-lg font-semibold">{it.value}</div>
        </div>
      ))}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border p-4">
      <h2 className="mb-3 text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export default function EtfDetailPage() {
  const params = useParams<{ ticker: string }>();
  const ticker = decodeURIComponent(params.ticker);
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState<string>("");
  const [snap, setSnap] = useState<EtfSnapshot | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getEtfSnapshotDates(ticker)
      .then((ds) => {
        setDates(ds);
        setDate(ds[0] ?? "");
      })
      .catch(() => setDates([]));
  }, [ticker]);

  const load = useCallback(() => {
    if (!date) {
      setSnap(null);
      return;
    }
    setLoading(true);
    getEtfSnapshot(ticker, date)
      .then(setSnap)
      .catch(() => setSnap(null))
      .finally(() => setLoading(false));
  }, [ticker, date]);

  useEffect(() => {
    load();
  }, [load]);

  const cat = (name: string) => snap?.categories?.[name]?.payload;

  return (
    <main className="mx-auto max-w-4xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground">
          <ArrowLeft className="h-4 w-4" /> 返回
        </Link>
        <h1 className="text-lg font-bold">{ticker}</h1>
        <select
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="rounded-md border px-2 py-1 text-sm"
        >
          {dates.length === 0 ? <option value="">无快照</option> : null}
          {dates.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
      </div>

      {loading ? <p className="text-sm text-muted-foreground">加载中…</p> : null}
      {!date ? <p className="text-sm text-muted-foreground">该 ETF 当天无数据快照。</p> : null}

      <Section title="分时价格"><IntradayChart payload={cat("intraday")} /></Section>
      <Section title="技术指标 / 日线"><DailyChart payload={cat("indicators")} /></Section>
      <Section title="新闻">
        {cat("news")?.text ? <MarkdownContent content={cat("news").text} /> : <MissingNote />}
      </Section>
      <Section title="基本面"><Fundamentals payload={cat("fundamentals")} /></Section>
    </main>
  );
}
```

- [ ] **Step 2: 类型检查 / 构建通过**

Run: `cd webui && npx tsc --noEmit`
Expected: 无类型错误(若 `MarkdownContent` 的 props 名不同,按其实际签名调整 —— 先读该组件确认 prop 名再改)。

- [ ] **Step 3: 提交**

```bash
git add webui/app/etf
git commit -m "feat(webui): add ETF detail page with date-selectable snapshot view"
```

---

### Task 12: 输入类型标注(ticker 路由返回 type) + watchlist 链接进详情页

**Files:**
- Modify: `api/routes/ticker.py`(返回 `type`)
- Modify: `webui/lib/api.ts`(`lookupTicker` 返回值加 `type`)
- Modify: `webui/components/ConfigCard.tsx`(`TickerItem` 加 `type`;渲染类型徽章 + ticker 链接进详情页)
- Test: `tests/webui/test_routes_ticker.py`

**Interfaces:**
- Consumes: `resolve_symbol_type`(Task 5 Step 0);`getEtfSnapshotDates` 路由已由 Task 9 提供;详情页 `/etf/[ticker]` 由 Task 11 提供。

- [ ] **Step 1: 后端失败测试**

```python
# tests/webui/test_routes_ticker.py
from fastapi.testclient import TestClient


def test_ticker_lookup_returns_type():
    from api.main import app

    client = TestClient(app)
    assert client.get("/api/ticker/510300.SS").json()["type"] == "etf"
    assert client.get("/api/ticker/600519.SS").json()["type"] == "stock"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_ticker.py -v`
Expected: FAIL(`KeyError: 'type'`)。

- [ ] **Step 3: 后端实现** —— 改 `api/routes/ticker.py`:

```python
"""Ticker route: resolve a single code to its company name + type (read-only)."""

from fastapi import APIRouter

from tradingagents.dataflows.ticker_name import resolve_ticker_name
from tradingagents.dataflows.tushare_utils import resolve_symbol_type

router = APIRouter(prefix="/api/ticker", tags=["ticker"])


@router.get("/{code}")
def lookup_ticker(code: str) -> dict:
    ticker = code.strip().upper()
    name = resolve_ticker_name(ticker)
    return {
        "ticker": ticker,
        "name": name,
        "valid": bool(name),
        "type": resolve_symbol_type(ticker),
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/webui/test_routes_ticker.py -v`
Expected: PASS。

- [ ] **Step 5: 前端 `lookupTicker` 带回 type** —— 改 `webui/lib/api.ts`(错误分支不带 type,故设为可选):

```typescript
export async function lookupTicker(
  code: string,
): Promise<{ ticker: string; name: string | null; valid: boolean; type?: "etf" | "stock" }> {
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

- [ ] **Step 6: ConfigCard 存 type + 徽章 + 详情页链接** —— 改 `webui/components/ConfigCard.tsx`:

`TickerItem` 类型(约 line 7)加 `type`:
```typescript
type TickerItem = { ticker: string; name: string; type?: "etf" | "stock" };
```

顶部 import 加 `Link`:
```typescript
import Link from "next/link";
```

两处 `lookupTicker` 命中后写回名称的地方(补查 effect 约 line 137、新增项约 line 164),把 `type` 一并存下 —— 将
```typescript
prev.map((t) => (t.ticker === code ? { ...t, name: res.name as string } : t))
```
改为
```typescript
prev.map((t) => (t.ticker === code ? { ...t, name: res.name as string, type: res.type } : t))
```

渲染处(约 line 352-353)把裸 ticker 文本换成"链接 + 类型徽章":
```tsx
<span className="flex min-w-0 flex-1 items-baseline gap-2">
  <Link
    href={`/etf/${encodeURIComponent(t.ticker)}`}
    className="shrink-0 font-mono text-sm text-foreground hover:underline"
  >
    {t.ticker}
  </Link>
  {t.type ? (
    <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
      {t.type === "etf" ? "ETF" : "股票"}
    </span>
  ) : null}
  {t.name ? (
```
(其余 `t.name` 渲染块保持不变。)

- [ ] **Step 7: 前端类型检查**

Run: `cd webui && npx tsc --noEmit`
Expected: 无类型错误。

- [ ] **Step 8: 提交**

```bash
git add api/routes/ticker.py tests/webui/test_routes_ticker.py webui/lib/api.ts webui/components/ConfigCard.tsx
git commit -m "feat(webui): label ticker type on lookup and link watchlist items to detail page"
```

---

### Task 13: 全量验证 + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 前端类型检查 + 单测**

Run: `cd webui && npx tsc --noEmit && npx vitest run`
Expected: 无类型错误;vitest 全绿。

- [ ] **Step 2: 后端全量 lint + 测试**

Run:
```bash
cd "/Users/joseph/Home/Studio/Vibe Code Studio/TradingAgents" && .venv/bin/ruff check . && .venv/bin/python -m pytest -m "not integration" -q
```
Expected: ruff 无错;pytest 全绿(不含 integration)。

- [ ] **Step 3: 更新 CHANGELOG.md** —— 在 `## [Unreleased]` 下 `### Added` 追加:

```markdown
- 预取快照:每个标的分析开始前预取新闻/分时/日线指标/基本面并落库到 webui.db,
  新闻+行情快照 push 进新闻/市场分析师上下文(根治"分析丢数据")。新闻按标的类型
  确定性分流(ETF→get_etf_news,股票→get_news),不再依赖 LLM 选对工具;输入代码
  即标注类型(ETF/股票)。新增按日期查看四类数据的独立详情页。分时/日线来自 tushare
  `stk_mins`/`fund_daily`。
```

- [ ] **Step 4: 提交**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for prefetch snapshot with type-aware news routing"
```

---

## Self-Review(规划者自检)

**1. Spec 覆盖:**
- 根因 A(在线失败)→ Task 5 重试/missing + Task 8 pull 读快照 ✓
- 根因 B(LLM 没调工具)→ Task 6 state 字段 + Task 7 push 上下文 ✓
- 四类数据 → 新闻(Task 5 `_fetch_news`)、分时(Task 1)、日线指标(Task 2 + get_indicators 文本)、基本面(Task 3)✓
- 时机 C(每 ETF 分析前预取)→ Task 6 `real_graph_factory` 内预取 ✓
- 失败处理 B(重试带退避 + missing 继续)→ Task 5 `_run_with_retry` ✓
- 投喂 ③(push + DB pull)→ Task 7(push)+ Task 8(pull)✓
- 快照存 webui.db → Task 4 ✓;与 startup-cache 隔离(不同存储位置)✓
- 详情页(独立页 + 四类可视化 + 日期选择 + 空快照留空)→ Task 9/10/11 + Task 12 链接 ✓
- 分时源 tushare `stk_mins` + 积分风险优雅降级 → Task 1 Step 1 探活 + Task 5 missing 兜底 ✓
- 新闻按类型确定性分流(ETF→get_etf_news,股票→get_news)→ Task 5 Step 0 `resolve_symbol_type` + `_fetch_news` 分支 + Task 8 两工具对称短路 ✓
- 输入代码标注类型 → Task 12 ticker 路由返回 `type` + ConfigCard 徽章 ✓
- 范围边界(仅新闻按类型分流,其余三类股票跑时优雅 missing)→ Task 1-3 保持 ETF 取数,Task 5 `_run_with_retry` 兜 missing ✓

**2. 占位符扫描:** 无 TBD/TODO;每个代码步骤含完整代码。前端 `MarkdownContent` prop 名与 watchlist 渲染处以"先读/先 grep"步骤兜底,非占位。

**3. 类型一致性:** `SnapshotSummary.for_context()` 键(`news_text`/`quote`/`missing`)在 Task 5 定义,Task 7 `build_prefetch_block` 与 Task 6 测试一致消费;`get_snapshot` 返回结构(`{category:{status,payload,fetched_at}}`)在 Task 4 定义,Task 8/9 一致消费;`upsert_snapshot` 签名 Task 4 定义,Task 5 一致调用;`resolve_symbol_type` 在 Task 5 Step 0 定义,Task 5 `_fetch_news` 与 Task 12 ticker 路由一致消费;`lookupTicker` 返回 `type` 在 Task 12 定义,ConfigCard `TickerItem.type` 一致消费。

**已知需实现时确认的点(非阻塞):**
- tushare `stk_mins`/`fund_nav` 字段名以真实返回为准(Task 1 Step 1 探活时核对);
- `MarkdownContent` 的实际 prop 名(Task 11 Step 2 读组件确认);
- watchlist 渲染组件已定位为 `webui/components/ConfigCard.tsx`(徽章/链接约 line 137/164/352-353,行号以实际为准)。
