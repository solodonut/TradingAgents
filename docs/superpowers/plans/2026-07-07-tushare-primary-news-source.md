# Tushare 全面接管新闻资讯 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `tushare_news.py`,让 Tushare 成为个股新闻(公司公告 + 关键词过滤快讯)和全局新闻(快讯 + 长篇 + 新闻联播)的主要来源,并接入路由 + 默认配置,保留现有源兜底。

**Architecture:** 单个新模块 `tradingagents/dataflows/tushare_news.py` 暴露 `get_news` / `get_global_news` 两个函数,严格对齐现有 news vendor 契约(非 A 股抛 `NoMarketDataError`、失败返回 `Error fetching news` 哨兵、输出 `## <label> News, from <s> to <e>:` 文档、日期前视安全过滤)。复用 `tushare_utils` 已有基建(`get_tushare_client` / `call_tushare` / `cached_call` / `to_ts_code` / `display_symbol` / `is_a_share`)与 `ticker_name.resolve_ticker_name`。最后在 `interface.py` 注册 vendor 并改 `default_config.py` 让 Tushare 开箱即用。

**Tech Stack:** Python ≥3.10, pandas, tushare(Pro API), pytest(全 mock,不打真实 API)。

## Global Constraints

- Python ≥ 3.10;运行 Python/pytest 一律用 `.venv/bin/python`(系统 python 可能是 3.9)。
- 数据源绝不直连:新代码只通过既有 `tushare_utils` 基建访问 Tushare;失败绝不抛裸异常给分析师 prompt,而是返回 `Error fetching news for <label>: <e>` 哨兵或让 `NoMarketDataError`/`TushareNotConfiguredError` 冒泡给 `route_to_vendor` 降级。
- news vendor 契约(与 `akshare_news.py` / `yfinance_news.py` 完全一致):
  - `get_news(ticker, start_date, end_date) -> str`;非 A 股抛 `NoMarketDataError`。
  - `get_global_news(curr_date, look_back_days=None, limit=None) -> str`。
  - 输出文档:`## <label> News, from <start> to <end>:` / `## Global Market News, from <start> to <end>:`,每条 `### <标题> (source: <来源>)`。
  - 前视安全:严禁返回 `end_date` / `curr_date` 之后发布的条目。
- 缓存:所有拉取走 `tushare_utils.cached_call(key, 3600, fn)`,`_NEWS_TTL_SECONDS = 3600`。
- 收尾必须手动跑 `.venv/bin/ruff check .` 和 `.venv/bin/python -m pytest -m "not integration"`(无 CI)。
- 提交:Conventional Commits;同步维护 `CHANGELOG.md`(Keep a Changelog)。

---

### Task 1: `tushare_news.get_news`(个股:公司公告 + 关键词过滤快讯)

**Files:**
- Create: `tradingagents/dataflows/tushare_news.py`
- Test: `tests/test_tushare_news.py`

**Interfaces:**
- Consumes(来自 `tushare_utils`,已存在): `get_tushare_client()`、`call_tushare(func)`、`cached_call(key, ttl, func)`、`to_ts_code(symbol) -> str`、`display_symbol(symbol) -> str`、`is_a_share(symbol) -> bool`(从 `.akshare_utils` 经 `tushare_utils` 或直接 import);`ticker_name.resolve_ticker_name(code) -> str | None`。
- Produces(供 Task 3 注册): `get_news(ticker: str, start_date: str, end_date: str) -> str`。模块内部还会定义 `_NEWS_TTL_SECONDS = 3600`、`_compact(d) -> str`、`_flash_dt(d, end=False) -> str`、`_fetch_anns(ts_code, start, end) -> pd.DataFrame`、`_fetch_flash(src, start, end) -> pd.DataFrame`(Task 2 复用)。

Tushare 接口返回列约定(用于 mock):
- `anns_d`: `ann_date`(YYYYMMDD 字符串)、`title`、`url`。
- `news`: `datetime`(`YYYY-MM-DD HH:MM:SS`)、`title`、`content`。

- [ ] **Step 1: Write the failing test**

创建 `tests/test_tushare_news.py`:

```python
from __future__ import annotations

from unittest import mock

import pandas as pd
import pytest

from tradingagents.dataflows import tushare_news
from tradingagents.dataflows.errors import NoMarketDataError


@pytest.fixture(autouse=True)
def _bypass_cache(monkeypatch):
    # cached_call 会写磁盘并跨用例命中;单测里直接透传,隔离每个用例。
    monkeypatch.setattr(tushare_news, "cached_call", lambda key, ttl, fn: fn())


def _fake_client(anns=None, news=None):
    client = mock.Mock()
    client.anns_d = mock.Mock(return_value=anns if anns is not None else pd.DataFrame())
    client.news = mock.Mock(return_value=news if news is not None else pd.DataFrame())
    return client


@pytest.mark.unit
def test_get_news_non_a_share_raises():
    with pytest.raises(NoMarketDataError):
        tushare_news.get_news("AAPL", "2026-06-01", "2026-06-30")


@pytest.mark.unit
def test_get_news_merges_announcements_and_flash(monkeypatch):
    anns = pd.DataFrame(
        [{"ann_date": "20260610", "title": "贵州茅台业绩预告", "url": "http://x/1.pdf"}]
    )
    news = pd.DataFrame(
        [
            {"datetime": "2026-06-12 09:00:00", "title": "茅台涨停", "content": "贵州茅台大涨"},
            {"datetime": "2026-06-12 09:05:00", "title": "无关新闻", "content": "别的公司"},
        ]
    )
    monkeypatch.setattr(tushare_news, "get_tushare_client", lambda: _fake_client(anns, news))
    monkeypatch.setattr(tushare_news, "resolve_ticker_name", lambda code: "贵州茅台")

    out = tushare_news.get_news("600519.SH", "2026-06-01", "2026-06-30")

    assert out.startswith("## 600519.SS News, from 2026-06-01 to 2026-06-30:")
    assert "业绩预告 (source: 公司公告)" in out
    assert "Link: http://x/1.pdf" in out
    assert "茅台涨停" in out          # 命中关键词的快讯保留
    assert "无关新闻" not in out       # 未命中的快讯被过滤
    # 公告排在快讯之前
    assert out.index("业绩预告") < out.index("茅台涨停")


@pytest.mark.unit
def test_get_news_name_lookup_failure_uses_announcements_only(monkeypatch):
    anns = pd.DataFrame([{"ann_date": "20260610", "title": "公告A", "url": "http://x/a.pdf"}])
    news = pd.DataFrame([{"datetime": "2026-06-12 09:00:00", "title": "某新闻", "content": "内容"}])
    monkeypatch.setattr(tushare_news, "get_tushare_client", lambda: _fake_client(anns, news))
    monkeypatch.setattr(tushare_news, "resolve_ticker_name", lambda code: None)

    out = tushare_news.get_news("600519.SH", "2026-06-01", "2026-06-30")

    assert "公告A" in out
    assert "某新闻" not in out          # 无关键词 -> 快讯路跳过


@pytest.mark.unit
def test_get_news_one_path_failure_degrades(monkeypatch):
    client = mock.Mock()
    client.anns_d = mock.Mock(side_effect=Exception("anns down"))
    client.news = mock.Mock(
        return_value=pd.DataFrame(
            [{"datetime": "2026-06-12 09:00:00", "title": "茅台新闻", "content": "贵州茅台"}]
        )
    )
    monkeypatch.setattr(tushare_news, "get_tushare_client", lambda: client)
    monkeypatch.setattr(tushare_news, "resolve_ticker_name", lambda code: "贵州茅台")

    out = tushare_news.get_news("600519.SH", "2026-06-01", "2026-06-30")

    assert "茅台新闻" in out            # 公告挂了,快讯仍返回
    assert not out.startswith("Error fetching news")


@pytest.mark.unit
def test_get_news_both_paths_fail_returns_sentinel(monkeypatch):
    client = mock.Mock()
    client.anns_d = mock.Mock(side_effect=Exception("anns down"))
    client.news = mock.Mock(side_effect=Exception("news down"))
    monkeypatch.setattr(tushare_news, "get_tushare_client", lambda: client)
    monkeypatch.setattr(tushare_news, "resolve_ticker_name", lambda code: "贵州茅台")

    out = tushare_news.get_news("600519.SH", "2026-06-01", "2026-06-30")

    assert out.startswith("Error fetching news for 600519.SS")


@pytest.mark.unit
def test_get_news_lookahead_filter(monkeypatch):
    anns = pd.DataFrame()
    news = pd.DataFrame(
        [
            {"datetime": "2026-06-15 09:00:00", "title": "窗口内茅台", "content": "贵州茅台"},
            {"datetime": "2026-07-20 09:00:00", "title": "未来茅台", "content": "贵州茅台"},
        ]
    )
    monkeypatch.setattr(tushare_news, "get_tushare_client", lambda: _fake_client(anns, news))
    monkeypatch.setattr(tushare_news, "resolve_ticker_name", lambda code: "贵州茅台")

    out = tushare_news.get_news("600519.SH", "2026-06-01", "2026-06-30")

    assert "窗口内茅台" in out
    assert "未来茅台" not in out        # end_date 之后的被丢弃


@pytest.mark.unit
def test_get_news_empty_returns_no_news(monkeypatch):
    monkeypatch.setattr(
        tushare_news, "get_tushare_client", lambda: _fake_client(pd.DataFrame(), pd.DataFrame())
    )
    monkeypatch.setattr(tushare_news, "resolve_ticker_name", lambda code: "贵州茅台")

    out = tushare_news.get_news("600519.SH", "2026-06-01", "2026-06-30")

    assert out == "No news found for 600519.SS between 2026-06-01 and 2026-06-30"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tushare_news.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'tradingagents.dataflows.tushare_news'`)

- [ ] **Step 3: Write minimal implementation**

创建 `tradingagents/dataflows/tushare_news.py`:

```python
"""Tushare Pro 新闻资讯:个股(公司公告 + 关键词过滤快讯)与全局(快讯 + 长篇 + 新闻联播)。

Tushare 的快讯流(``news`` / ``major_news``)是通用 feed,不支持按个股搜索,所以个股新闻
靠 ``anns_d`` 公司公告(真·按 ts_code)+ 用股票中文名/代码在快讯正文里 ``contains`` 过滤。
契约与 ``akshare_news`` / ``yfinance_news`` 完全一致,``route_to_vendor`` 可透明切换。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import pandas as pd
from dateutil.relativedelta import relativedelta

from .akshare_utils import is_a_share
from .config import get_config
from .errors import NoMarketDataError
from .ticker_name import resolve_ticker_name
from .tushare_utils import (
    cached_call,
    call_tushare,
    display_symbol,
    get_tushare_client,
    to_ts_code,
)

# 快讯流 intraday 波动大;1h 缓存收敛单次分析的重复调用(与 akshare_news 一致)。
_NEWS_TTL_SECONDS = 3600


def _compact(date_str: str) -> str:
    return date_str.replace("-", "")


def _flash_dt(date_str: str, end: bool = False) -> str:
    # tushare ``news`` / ``major_news`` 的 start_date/end_date 用 'YYYY-MM-DD HH:MM:SS'。
    return f"{date_str} 23:59:59" if end else f"{date_str} 00:00:00"


def _fetch_anns(ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    key = f"anns_d/{ts_code}/{_compact(start_date)}/{_compact(end_date)}"

    def _fetch():
        client = get_tushare_client()
        return call_tushare(
            lambda: client.anns_d(
                ts_code=ts_code,
                start_date=_compact(start_date),
                end_date=_compact(end_date),
            )
        )

    return cached_call(key, _NEWS_TTL_SECONDS, _fetch)


def _fetch_flash(src: str, start_date: str, end_date: str) -> pd.DataFrame:
    key = f"news/{src}/{_compact(start_date)}/{_compact(end_date)}"

    def _fetch():
        client = get_tushare_client()
        return call_tushare(
            lambda: client.news(
                src=src,
                start_date=_flash_dt(start_date),
                end_date=_flash_dt(end_date, end=True),
            )
        )

    return cached_call(key, _NEWS_TTL_SECONDS, _fetch)


def _render_anns(df: pd.DataFrame) -> list[tuple[datetime, str]]:
    rows = []
    if df is None or df.empty:
        return rows
    for _, row in df.iterrows():
        pub = pd.to_datetime(row.get("ann_date"), errors="coerce")
        if pd.isna(pub):
            continue
        title = row.get("title", "无标题")
        url = row.get("url", "")
        block = f"### {title} (source: 公司公告)\n"
        if isinstance(url, str) and url.strip():
            block += f"Link: {url.strip()}\n"
        block += "\n"
        rows.append((pub.to_pydatetime(), block))
    return rows


def _render_flash(df: pd.DataFrame, keywords: list[str], start_dt, end_dt, src_label="快讯"):
    rows = []
    if df is None or df.empty:
        return rows
    for _, row in df.iterrows():
        pub = pd.to_datetime(row.get("datetime"), errors="coerce")
        if pd.isna(pub) or not (start_dt <= pub.to_pydatetime() <= end_dt):
            continue
        title = row.get("title") or ""
        content = row.get("content") or ""
        haystack = f"{title}{content}"
        if keywords and not any(k in haystack for k in keywords):
            continue
        display_title = title.strip() if isinstance(title, str) and title.strip() else "快讯"
        block = f"### {display_title} (source: {src_label})\n"
        if isinstance(content, str) and content.strip():
            block += f"{content.strip()}\n"
        block += "\n"
        rows.append((pub.to_pydatetime(), block))
    return rows


def get_news(
    ticker: Annotated[str, "A-share ticker (600519, 600519.SH, ...)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """个股新闻:公司公告(anns_d)+ 关键词过滤快讯(news),合并按时间倒序。"""
    if not is_a_share(ticker):
        raise NoMarketDataError(ticker, "not an A-share; no Tushare company news")

    ts_code = to_ts_code(ticker)
    label = display_symbol(ticker)
    article_limit = get_config()["news_article_limit"]

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + relativedelta(days=1)

    anns_err = flash_err = None
    anns_rows = flash_rows = []

    try:
        anns_rows = _render_anns(_fetch_anns(ts_code, start_date, end_date))
    except Exception as e:  # 单路失败降级,不整体报错
        anns_err = e

    name = resolve_ticker_name(ticker)
    code_only = ts_code.split(".")[0]
    keywords = [k for k in (name, code_only) if k]
    if keywords:
        try:
            flash_rows = _render_flash(
                _fetch_flash("sina", start_date, end_date), keywords, start_dt, end_dt
            )
        except Exception as e:
            flash_err = e

    if anns_err is not None and (flash_err is not None or not keywords) and not anns_rows and not flash_rows:
        return f"Error fetching news for {label}: {anns_err or flash_err}"

    # 公告在前(更硬),再按时间倒序拼快讯。
    ordered = anns_rows + sorted(flash_rows, key=lambda r: r[0], reverse=True)
    ordered = ordered[:article_limit]

    if not ordered:
        return f"No news found for {label} between {start_date} and {end_date}"

    body = "".join(block for _, block in ordered)
    return f"## {label} News, from {start_date} to {end_date}:\n\n{body}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_tushare_news.py -v`
Expected: PASS(7 passed)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/tushare_news.py tests/test_tushare_news.py
git commit -m "feat(dataflows): add Tushare per-stock news (anns_d + keyword-filtered flash)"
```

---

### Task 2: `tushare_news.get_global_news`(全局:快讯 + 长篇 + 新闻联播)

**Files:**
- Modify: `tradingagents/dataflows/tushare_news.py`(追加 `get_global_news` 及 `_fetch_major` / `_fetch_cctv`)
- Test: `tests/test_tushare_news.py`(追加全局新闻用例)

**Interfaces:**
- Consumes: Task 1 的 `_NEWS_TTL_SECONDS`、`_compact`、`_flash_dt`、`_fetch_flash`、`_render_flash`、`cached_call`、`call_tushare`、`get_tushare_client`、`get_config`。
- Produces(供 Task 3 注册): `get_global_news(curr_date: str, look_back_days: int | None = None, limit: int | None = None) -> str`。

Tushare 接口返回列约定(用于 mock):
- `major_news`: `pub_time`(`YYYY-MM-DD HH:MM:SS`)、`title`、`content`。
- `cctv_news`: `date`(YYYYMMDD)、`title`、`content`。

配置约定:`tushare_news_flash_sources`(list 或逗号串)默认 `["sina", "wallstreetcn"]`。

- [ ] **Step 1: Write the failing test**

在 `tests/test_tushare_news.py` 末尾追加:

```python
def _fake_global_client(flash_by_src=None, major=None, cctv=None):
    client = mock.Mock()
    flash_by_src = flash_by_src or {}
    client.news = mock.Mock(side_effect=lambda src, **kw: flash_by_src.get(src, pd.DataFrame()))
    client.major_news = mock.Mock(return_value=major if major is not None else pd.DataFrame())
    client.cctv_news = mock.Mock(return_value=cctv if cctv is not None else pd.DataFrame())
    return client


@pytest.mark.unit
def test_global_news_merges_three_sources(monkeypatch):
    flash = {
        "sina": pd.DataFrame([{"datetime": "2026-07-05 09:00:00", "title": "快讯A", "content": "c1"}]),
        "wallstreetcn": pd.DataFrame([{"datetime": "2026-07-05 10:00:00", "title": "快讯B", "content": "c2"}]),
    }
    major = pd.DataFrame([{"pub_time": "2026-07-04 08:00:00", "title": "长篇C", "content": "c3"}])
    cctv = pd.DataFrame([{"date": "20260706", "title": "联播D", "content": "c4"}])

    monkeypatch.setattr(
        tushare_news, "get_tushare_client",
        lambda: _fake_global_client(flash, major, cctv),
    )

    out = tushare_news.get_global_news("2026-07-07", look_back_days=7, limit=10)

    assert out.startswith("## Global Market News, from 2026-06-30 to 2026-07-07:")
    for token in ("快讯A", "快讯B", "长篇C", "联播D"):
        assert token in out
    assert "(source: 长篇)" in out
    assert "(source: 新闻联播)" in out


@pytest.mark.unit
def test_global_news_dedupes_and_limits(monkeypatch):
    flash = {
        "sina": pd.DataFrame(
            [
                {"datetime": "2026-07-05 09:00:00", "title": "重复标题", "content": "x"},
                {"datetime": "2026-07-05 08:00:00", "title": "重复标题", "content": "y"},
                {"datetime": "2026-07-05 07:00:00", "title": "唯一", "content": "z"},
            ]
        ),
    }
    monkeypatch.setattr(
        tushare_news, "get_tushare_client",
        lambda: _fake_global_client(flash, pd.DataFrame(), pd.DataFrame()),
    )

    out = tushare_news.get_global_news("2026-07-07", look_back_days=7, limit=10)

    assert out.count("重复标题") == 1     # 同标题去重
    assert "唯一" in out


@pytest.mark.unit
def test_global_news_cctv_iterates_days(monkeypatch):
    calls = []

    def _news(src, **kw):
        return pd.DataFrame()

    def _cctv(date):
        calls.append(date)
        return pd.DataFrame([{"date": date, "title": f"联播{date}", "content": "c"}])

    client = mock.Mock()
    client.news = mock.Mock(side_effect=_news)
    client.major_news = mock.Mock(return_value=pd.DataFrame())
    client.cctv_news = mock.Mock(side_effect=_cctv)
    monkeypatch.setattr(tushare_news, "get_tushare_client", lambda: client)

    tushare_news.get_global_news("2026-07-07", look_back_days=2, limit=10)

    assert set(calls) == {"20260705", "20260706", "20260707"}   # 窗口内每天一次


@pytest.mark.unit
def test_global_news_all_fail_returns_message(monkeypatch):
    client = mock.Mock()
    client.news = mock.Mock(side_effect=Exception("down"))
    client.major_news = mock.Mock(side_effect=Exception("down"))
    client.cctv_news = mock.Mock(side_effect=Exception("down"))
    monkeypatch.setattr(tushare_news, "get_tushare_client", lambda: client)

    out = tushare_news.get_global_news("2026-07-07", look_back_days=7, limit=10)

    assert out.startswith("Error fetching global news")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tushare_news.py -k global -v`
Expected: FAIL(`AttributeError: module ... has no attribute 'get_global_news'`)

- [ ] **Step 3: Write minimal implementation**

在 `tushare_news.py` 追加(import 处补 `from datetime import datetime, timedelta` — 若已 `from datetime import datetime`,改成同时导入 `timedelta`):

```python
def _fetch_major(start_date: str, end_date: str) -> pd.DataFrame:
    key = f"major_news/{_compact(start_date)}/{_compact(end_date)}"

    def _fetch():
        client = get_tushare_client()
        return call_tushare(
            lambda: client.major_news(
                start_date=_flash_dt(start_date),
                end_date=_flash_dt(end_date, end=True),
            )
        )

    return cached_call(key, _NEWS_TTL_SECONDS, _fetch)


def _fetch_cctv(date_compact: str) -> pd.DataFrame:
    key = f"cctv_news/{date_compact}"

    def _fetch():
        client = get_tushare_client()
        return call_tushare(lambda: client.cctv_news(date=date_compact))

    return cached_call(key, _NEWS_TTL_SECONDS, _fetch)


def _flash_sources() -> list[str]:
    raw = get_config().get("tushare_news_flash_sources") or ["sina", "wallstreetcn"]
    if isinstance(raw, str):
        raw = [s.strip() for s in raw.split(",") if s.strip()]
    return list(raw)


def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """全局新闻:news(多 src)+ major_news + cctv_news,合并去重按时间倒序。"""
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]

    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - relativedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")
    window_end = curr_dt + relativedelta(days=1)

    rows: list[tuple[datetime, str]] = []
    errors = 0

    for src in _flash_sources():
        try:
            rows += _render_flash(
                _fetch_flash(src, start_date, curr_date), [], start_dt, window_end,
                src_label=f"快讯/{src}",
            )
        except Exception:
            errors += 1

    try:
        major = _fetch_major(start_date, curr_date)
        if major is not None and not major.empty:
            major = major.rename(columns={"pub_time": "datetime"})
            rows += _render_flash(major, [], start_dt, window_end, src_label="长篇")
    except Exception:
        errors += 1

    day = start_dt
    while day <= curr_dt:
        try:
            cctv = _fetch_cctv(day.strftime("%Y%m%d"))
            if cctv is not None and not cctv.empty:
                cctv = cctv.copy()
                cctv["datetime"] = pd.to_datetime(cctv.get("date"), format="%Y%m%d", errors="coerce")
                rows += _render_flash(cctv, [], start_dt, window_end, src_label="新闻联播")
        except Exception:
            errors += 1
        day += timedelta(days=1)

    if not rows and errors:
        return f"Error fetching global news for {curr_date}: all Tushare news sources failed"

    # 按时间倒序,标题去重(块内首行 '### <title> (source: ...)')。
    rows.sort(key=lambda r: r[0], reverse=True)
    seen: set[str] = set()
    body = ""
    kept = 0
    for _, block in rows:
        title_line = block.split("\n", 1)[0]
        if title_line in seen:
            continue
        seen.add(title_line)
        body += block
        kept += 1
        if kept >= limit:
            break

    if kept == 0:
        return f"No global news found between {start_date} and {curr_date}"

    return f"## Global Market News, from {start_date} to {curr_date}:\n\n{body}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_tushare_news.py -v`
Expected: PASS(11 passed)

> 注:`test_global_news_dedupes_and_limits` 依赖标题去重 —— `_render_flash` 生成的块首行含标题,`get_global_news` 按首行去重。若两条同标题快讯的首行完全一致即去重通过。

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/tushare_news.py tests/test_tushare_news.py
git commit -m "feat(dataflows): add Tushare global news (flash + major + CCTV)"
```

---

### Task 3: 路由注册 + 默认配置 + 文档

**Files:**
- Modify: `tradingagents/dataflows/interface.py`(import + `VENDOR_METHODS` 两处注册)
- Modify: `tradingagents/default_config.py`(`tool_vendors` 两条 + 新增 `tushare_news_flash_sources`)
- Modify: `.env.example`(补 `TRADINGAGENTS_TUSHARE_NEWS_FLASH_SOURCES` 说明)
- Modify: `CHANGELOG.md`
- Test: `tests/test_tushare_news.py`(追加路由用例)

**Interfaces:**
- Consumes: Task 1/2 的 `get_news`、`get_global_news`;`interface.route_to_vendor(method, *args, **kwargs)`。
- Produces: 无新符号;改变默认路由行为。

- [ ] **Step 1: Write the failing test**

在 `tests/test_tushare_news.py` 末尾追加(顶部补 `from tradingagents.dataflows import interface`、`from tradingagents.dataflows.config import set_config`):

```python
@pytest.mark.unit
def test_route_get_news_hits_tushare(monkeypatch):
    set_config({"tool_vendors": {"get_news": "tushare,akshare,eastmoney"}})
    called = {}

    def _fake(ticker, start, end):
        called["hit"] = ticker
        return "## 600519.SS News, from 2026-06-01 to 2026-06-30:\n\nok"

    monkeypatch.setitem(interface.VENDOR_METHODS["get_news"], "tushare", _fake)

    out = interface.route_to_vendor("get_news", "600519.SH", "2026-06-01", "2026-06-30")

    assert called["hit"] == "600519.SH"
    assert out.startswith("## 600519.SS News")


@pytest.mark.unit
def test_route_get_global_news_hits_tushare(monkeypatch):
    set_config({"tool_vendors": {"get_global_news": "tushare,yfinance"}})

    monkeypatch.setitem(
        interface.VENDOR_METHODS["get_global_news"], "tushare",
        lambda curr_date, **kw: "## Global Market News, from 2026-06-30 to 2026-07-07:\n\nok",
    )

    out = interface.route_to_vendor("get_global_news", "2026-07-07")

    assert out.startswith("## Global Market News")
```

> `interface.VENDOR_METHODS["get_news"]` 目前无 `"tushare"` 键,`monkeypatch.setitem` 会新增它;测试通过不代表注册已落地 —— Step 3 的静态注册才是交付物。这两个用例锁定「Tushare 出现在 news 路由里且可被 route_to_vendor 命中」。

- [ ] **Step 2: Run test to verify it fails**

先只跑不改代码,确认路由能力:
Run: `.venv/bin/python -m pytest tests/test_tushare_news.py -k route -v`
Expected: PASS(monkeypatch 动态注入即可通过)—— 说明路由机制正确。真正的静态注册在 Step 3;跑全量回归验证未破坏其它测试。

- [ ] **Step 3: Write the implementation**

**3a.** `tradingagents/dataflows/interface.py` —— 在 tushare import 区(约 44–52 行)后补:

```python
from .tushare_news import get_global_news as get_tushare_global_news, get_news as get_tushare_news
```

在 `VENDOR_METHODS["get_news"]` 字典加一行:

```python
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
        "longbridge": get_longbridge_news,
        "akshare": get_akshare_news,
        "eastmoney": get_eastmoney_news,
        "tushare": get_tushare_news,
    },
```

在 `VENDOR_METHODS["get_global_news"]` 字典加一行:

```python
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
        "tushare": get_tushare_global_news,
    },
```

**3b.** `tradingagents/default_config.py`:

- 把 `tool_vendors["get_news"]` 从 `"akshare,eastmoney,longbridge"` 改成 `"tushare,akshare,eastmoney"`。
- 在 `tool_vendors` 里新增一行:`"get_global_news": "tushare,yfinance",`。
- 在 news 相关配置附近(`global_news_queries` 之后)新增:

```python
    # Tushare 快讯 news() 的数据源列表(单次调用只能传一个 src,逐源合并)。
    # 可选:sina / wallstreetcn / 10jqka / eastmoney / yuncaijing 等。
    "tushare_news_flash_sources": ["sina", "wallstreetcn"],
```

**3c.** `.env.example` —— 在新闻相关变量附近补:

```bash
# Tushare 快讯 news() 数据源(逗号分隔),覆盖 default_config 的 tushare_news_flash_sources
# TRADINGAGENTS_TUSHARE_NEWS_FLASH_SOURCES=sina,wallstreetcn
```

**3d.** `CHANGELOG.md` —— 在 `## [Unreleased]` 的 `### Added` 下加:

```markdown
- Tushare 全面接管新闻资讯:新增 `tushare_news`,个股走公司公告(`anns_d`)+ 关键词过滤快讯(`news`),
  全局走快讯 + 长篇(`major_news`)+ 新闻联播(`cctv_news`);默认 `get_news`/`get_global_news` 以 Tushare 为主源。
```

- [ ] **Step 4: Run tests + lint**

```bash
.venv/bin/python -m pytest tests/test_tushare_news.py -v
.venv/bin/ruff check .
.venv/bin/python -m pytest -m "not integration" -q
```

Expected: `tests/test_tushare_news.py` 全绿;ruff 无新增报错;全量回归仍是 867 passed / 5 failed 基线(那 5 个是 main 上预存在失败,非本次回归)。若 `get_news` 默认链变更导致新增失败,检查是否有测试硬编码了旧的 `"akshare,eastmoney,longbridge"` 期望值并按需修正。

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/interface.py tradingagents/default_config.py .env.example CHANGELOG.md tests/test_tushare_news.py
git commit -m "feat(dataflows): route news through Tushare as primary source"
```

---

## Self-Review

**1. Spec coverage:**
- 模块 + 双函数契约 → Task 1/2 ✅
- 个股:anns_d + 关键词过滤快讯、公告在前、单路降级、名字失败只走公告、前视过滤、空返回 → Task 1 ✅
- 全局:news 多 src + major_news + cctv 按天 + 去重 + limit + 全失败错误串 → Task 2 ✅
- 路由注册 get_news/get_global_news、tool_vendors 两条、flash_sources 配置 → Task 3 ✅
- 缓存 1h、错误分层(call_tushare 归一 + NoMarketDataError 降级)→ Task 1/2 贯穿 ✅
- 文档 .env.example + CHANGELOG → Task 3 ✅
- YAGNI(不抓公告全文、不做语义排序、cctv 无单独开关)→ 已在实现里恪守 ✅

**2. Placeholder scan:** 无 TBD/TODO;每个 code step 都给了完整代码。✅

**3. Type consistency:** `get_news(ticker, start_date, end_date)`、`get_global_news(curr_date, look_back_days, limit)` 全篇一致;`_fetch_flash(src, start, end)` 被 Task 1/2 复用签名一致;`_render_flash(df, keywords, start_dt, end_dt, src_label)` 定义与调用一致;`_compact` / `_flash_dt` 一致。✅

**一个实现注意点(非阻塞):** `major_news` / `cctv` 复用 `_render_flash` 需先把各自时间列 rename/构造成 `datetime` 列 —— 已在 Task 2 实现中显式处理(`rename(columns={"pub_time": "datetime"})` 与 `cctv["datetime"] = ...`)。
