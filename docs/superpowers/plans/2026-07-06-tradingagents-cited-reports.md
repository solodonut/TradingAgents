# TradingAgents Cited Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add system-generated `[S#]` citations and source tables to TradingAgents reports across the full analysis chain.

**Architecture:** Add a serializable evidence registry plus a run-scoped provenance context based on `ContextVar`. Data tools register evidence through the context, agents receive citation instructions and return current evidence snapshots in graph state, and markdown report rendering expands cited ids into source tables.

**Tech Stack:** Python 3.10+, LangGraph state dicts, LangChain tools, Typer/FastAPI existing report pipeline, pytest, ruff.

---

## File Structure

- Create `tradingagents/graph/evidence.py`: evidence item normalization, id allocation, citation scanning, markdown source table rendering.
- Create `tradingagents/graph/provenance.py`: `ContextVar` current registry helpers, safe registration helpers for news/dataset/unavailable evidence, source-id prefixing.
- Create `tests/test_evidence.py`: unit tests for registry behavior and source table rendering.
- Create `tests/test_provenance.py`: unit tests for run-scoped context and registration helpers.
- Modify `tradingagents/agents/utils/agent_states.py`: add `evidence_items` to `AgentState`.
- Modify `tradingagents/graph/propagation.py`: initialize `evidence_items`.
- Modify `tradingagents/graph/trading_graph.py`: create/clear provenance context for CLI/direct runs.
- Modify `api/runner.py`: create/clear provenance context for WebUI background runs and ensure final state carries evidence.
- Modify `api/reporting.py`: render per-section and global citation source tables.
- Modify `tests/webui/test_routes_analysis.py`: assert report download expands source tables and old reports still work.
- Modify `tradingagents/agents/utils/news_data_tools.py`: register and prefix evidence for `get_news`, `get_global_news`, and `get_insider_transactions`.
- Modify `tradingagents/agents/utils/core_stock_tools.py`: register dataset evidence for `get_stock_data`.
- Modify `tradingagents/agents/utils/technical_indicators_tools.py`: register dataset evidence for `get_indicators`.
- Modify `tradingagents/agents/utils/fundamental_data_tools.py`: register dataset evidence for fundamentals and financial statements.
- Modify `tradingagents/agents/utils/market_data_validation_tools.py`: register dataset or unavailable evidence for verified snapshots.
- Modify `tradingagents/agents/analysts/sentiment_analyst.py`: register sentiment prefetch evidence and return evidence snapshots.
- Modify analyst/research/trader/risk/manager modules under `tradingagents/agents/`: append shared citation prompt instruction and return evidence snapshots from graph nodes.
- Modify `tradingagents/graph/report_validator.py`: append citation validation warnings to `validation_report`.
- Add focused tests in existing test files where behavior already lives.

## Success Criteria

- Tools expose system-created `[S#]` ids in their returned markdown.
- Generated reports can cite `[S#]` ids without agents inventing metadata.
- Downloaded markdown reports include per-section `引用来源` tables and a global `全部数据来源` table.
- Invalid citation ids are reported in `validation_report`.
- Old runs without `evidence_items` still download.
- `pytest -m "not integration"` passes.
- `ruff check .` passes.

---

### Task 1: Evidence Registry

**Files:**
- Create: `tradingagents/graph/evidence.py`
- Test: `tests/test_evidence.py`

- [ ] **Step 1: Write failing tests for registry allocation, dedupe, scanning, and rendering**

Create `tests/test_evidence.py`:

```python
import pytest

from tradingagents.graph.evidence import (
    EvidenceRegistry,
    extract_citation_ids,
    render_source_table,
)


@pytest.mark.unit
def test_register_allocates_stable_ids_and_dedupes():
    registry = EvidenceRegistry()

    first = registry.register(
        kind="news",
        source_name="财联社",
        title="半导体板块获政策支持",
        url="https://example.com/news/1",
        published_at="2026-07-01",
        vendor="akshare",
        tool_name="get_news",
        query={"ticker": "600519", "start_date": "2026-06-29", "end_date": "2026-07-06"},
        excerpt="政策支持增强。",
    )
    second = registry.register(
        kind="news",
        source_name="财联社",
        title="半导体板块获政策支持",
        url="https://example.com/news/1",
        published_at="2026-07-01",
        vendor="akshare",
        tool_name="get_news",
        query={"ticker": "600519", "start_date": "2026-06-29", "end_date": "2026-07-06"},
        excerpt="另一段摘要。",
    )
    third = registry.register(
        kind="market_data",
        source_name="AKShare",
        title="get_stock_data: 600519",
        vendor="akshare",
        tool_name="get_stock_data",
        query={"ticker": "600519", "start_date": "2026-06-29", "end_date": "2026-07-06"},
    )

    assert first == "S1"
    assert second == "S1"
    assert third == "S2"
    assert [item["id"] for item in registry.items] == ["S1", "S2"]
    assert registry.items[0]["excerpt"] == "政策支持增强。"


@pytest.mark.unit
def test_extract_citation_ids_preserves_first_seen_order():
    text = "事件改善 [S2]，成交放大 [S1]，重复引用 [S2]，非法 [S999]。"

    assert extract_citation_ids(text) == ["S2", "S1", "S999"]


@pytest.mark.unit
def test_render_source_table_uses_only_known_ids_and_links_urls():
    registry = EvidenceRegistry([
        {
            "id": "S1",
            "kind": "news",
            "source_name": "财联社",
            "title": "半导体板块获政策支持",
            "url": "https://example.com/news/1",
            "published_at": "2026-07-01",
            "vendor": "akshare",
            "tool_name": "get_news",
            "query": {"ticker": "600519"},
            "excerpt": "政策支持增强。",
        },
        {
            "id": "S2",
            "kind": "market_data",
            "source_name": "AKShare",
            "title": "get_stock_data: 600519",
            "url": "",
            "published_at": "2026-06-29..2026-07-06",
            "vendor": "akshare",
            "tool_name": "get_stock_data",
            "query": {"ticker": "600519"},
            "excerpt": "",
        },
    ])

    table = render_source_table(registry.items, ["S2", "S404", "S1"], heading="引用来源")

    assert "### 引用来源" in table
    assert "| [S2] | AKShare | get_stock_data: 600519 | 2026-06-29..2026-07-06 | - |" in table
    assert "| [S1] | 财联社 | 半导体板块获政策支持 | 2026-07-01 | [打开](https://example.com/news/1) |" in table
    assert "S404" not in table
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_evidence.py -v
```

Expected: FAIL during import with `ModuleNotFoundError: No module named 'tradingagents.graph.evidence'`.

- [ ] **Step 3: Implement `tradingagents/graph/evidence.py`**

Create `tradingagents/graph/evidence.py`:

```python
"""Evidence registry and markdown citation helpers."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

_CITATION_RE = re.compile(r"\[S(\d+)\]")


def extract_citation_ids(text: str) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for match in _CITATION_RE.finditer(text or ""):
        citation_id = f"S{match.group(1)}"
        if citation_id not in seen:
            seen.add(citation_id)
            ids.append(citation_id)
    return ids


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value)


def _safe_cell(value: Any) -> str:
    text = _display(value) or "-"
    return html.escape(text).replace("|", "\\|")


def _dedupe_key(item: Mapping[str, Any]) -> tuple:
    query = item.get("query") or {}
    if isinstance(query, Mapping):
        query_key = tuple(sorted((str(k), str(v)) for k, v in query.items()))
    else:
        query_key = str(query)
    return (
        item.get("kind") or "",
        item.get("source_name") or "",
        item.get("title") or "",
        item.get("url") or "",
        item.get("tool_name") or "",
        query_key,
    )


def _normalize_item(item: Mapping[str, Any], citation_id: str) -> dict[str, Any]:
    return {
        "id": citation_id,
        "kind": _display(item.get("kind")) or "vendor_dataset",
        "source_name": _display(item.get("source_name")) or _display(item.get("vendor")) or "unknown",
        "title": _display(item.get("title")) or _display(item.get("tool_name")) or "Untitled evidence",
        "url": _display(item.get("url")),
        "published_at": _display(item.get("published_at")),
        "vendor": _display(item.get("vendor")),
        "tool_name": _display(item.get("tool_name")),
        "query": deepcopy(item.get("query") or {}),
        "excerpt": _display(item.get("excerpt")),
    }


class EvidenceRegistry:
    def __init__(self, items: Iterable[Mapping[str, Any]] | None = None):
        self.items: list[dict[str, Any]] = []
        self._keys: dict[tuple, str] = {}
        max_seen = 0
        for raw in items or []:
            raw_id = _display(raw.get("id"))
            citation_id = raw_id if raw_id.startswith("S") and raw_id[1:].isdigit() else f"S{max_seen + 1}"
            normalized = _normalize_item(raw, citation_id)
            self.items.append(normalized)
            self._keys[_dedupe_key(normalized)] = citation_id
            max_seen = max(max_seen, int(citation_id[1:]))
        self._next = max_seen + 1

    def register(self, **item: Any) -> str:
        provisional = _normalize_item(item, "S0")
        key = _dedupe_key(provisional)
        existing = self._keys.get(key)
        if existing:
            return existing
        citation_id = f"S{self._next}"
        self._next += 1
        normalized = _normalize_item(item, citation_id)
        self.items.append(normalized)
        self._keys[_dedupe_key(normalized)] = citation_id
        return citation_id

    def to_list(self) -> list[dict[str, Any]]:
        return deepcopy(self.items)

    def by_id(self) -> dict[str, dict[str, Any]]:
        return {item["id"]: item for item in self.items}


def render_source_table(
    evidence_items: Iterable[Mapping[str, Any]],
    citation_ids: Iterable[str],
    *,
    heading: str,
) -> str:
    by_id = {item.get("id"): item for item in evidence_items}
    rows: list[str] = []
    for citation_id in citation_ids:
        item = by_id.get(citation_id)
        if not item:
            continue
        url = _display(item.get("url"))
        link = f"[打开]({url})" if url else "-"
        rows.append(
            "| "
            + " | ".join(
                [
                    f"[{citation_id}]",
                    _safe_cell(item.get("source_name")),
                    _safe_cell(item.get("title")),
                    _safe_cell(item.get("published_at")),
                    link,
                ]
            )
            + " |"
        )
    if not rows:
        return ""
    return "\n".join(
        [
            f"### {heading}",
            "",
            "| 编号 | 来源 | 标题/数据集 | 日期 | 链接 |",
            "|---|---|---|---|---|",
            *rows,
        ]
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_evidence.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/graph/evidence.py tests/test_evidence.py
git commit -m "feat(reports): add evidence registry"
```

---

### Task 2: Run-Scoped Provenance Context

**Files:**
- Create: `tradingagents/graph/provenance.py`
- Test: `tests/test_provenance.py`

- [ ] **Step 1: Write failing provenance tests**

Create `tests/test_provenance.py`:

```python
import pytest

from tradingagents.graph.evidence import EvidenceRegistry
from tradingagents.graph.provenance import (
    clear_current_evidence_registry,
    current_evidence_items,
    prefix_with_evidence,
    register_dataset_evidence,
    register_unavailable_evidence,
    set_current_evidence_registry,
)


@pytest.mark.unit
def test_context_registration_returns_snapshot_and_prefixes_text():
    registry = EvidenceRegistry()
    set_current_evidence_registry(registry)
    try:
        citation_id = register_dataset_evidence(
            kind="market_data",
            source_name="AKShare",
            title="get_stock_data: 600519",
            vendor="akshare",
            tool_name="get_stock_data",
            query={"ticker": "600519"},
            published_at="2026-06-29..2026-07-06",
        )
        assert citation_id == "S1"
        assert prefix_with_evidence("payload", citation_id, "OHLCV 数据集").startswith(
            "## [S1] OHLCV 数据集"
        )
        assert current_evidence_items()[0]["id"] == "S1"
    finally:
        clear_current_evidence_registry()


@pytest.mark.unit
def test_registration_is_noop_without_context():
    clear_current_evidence_registry()

    assert register_dataset_evidence(
        kind="market_data",
        source_name="AKShare",
        title="get_stock_data: 600519",
        vendor="akshare",
        tool_name="get_stock_data",
        query={"ticker": "600519"},
    ) is None
    assert current_evidence_items() == []


@pytest.mark.unit
def test_unavailable_evidence_can_be_registered():
    registry = EvidenceRegistry()
    set_current_evidence_registry(registry)
    try:
        citation_id = register_unavailable_evidence(
            tool_name="get_news",
            vendor="akshare",
            query={"ticker": "600519"},
            reason="DATA_SOURCE_UNAVAILABLE: network timeout",
        )
        assert citation_id == "S1"
        assert current_evidence_items()[0]["kind"] == "data_unavailable"
        assert current_evidence_items()[0]["title"] == "get_news unavailable"
    finally:
        clear_current_evidence_registry()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_provenance.py -v
```

Expected: FAIL during import with `ModuleNotFoundError: No module named 'tradingagents.graph.provenance'`.

- [ ] **Step 3: Implement provenance context**

Create `tradingagents/graph/provenance.py`:

```python
"""Run-scoped provenance context for evidence registration."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from tradingagents.graph.evidence import EvidenceRegistry

_current: ContextVar[EvidenceRegistry | None] = ContextVar("evidence_registry", default=None)


def set_current_evidence_registry(registry: EvidenceRegistry | None) -> None:
    _current.set(registry)


def get_current_evidence_registry() -> EvidenceRegistry | None:
    return _current.get()


def clear_current_evidence_registry() -> None:
    _current.set(None)


def current_evidence_items() -> list[dict[str, Any]]:
    registry = get_current_evidence_registry()
    return registry.to_list() if registry is not None else []


def register_dataset_evidence(
    *,
    kind: str,
    source_name: str,
    title: str,
    vendor: str,
    tool_name: str,
    query: dict[str, Any],
    published_at: str = "",
    excerpt: str = "",
    url: str = "",
) -> str | None:
    registry = get_current_evidence_registry()
    if registry is None:
        return None
    return registry.register(
        kind=kind,
        source_name=source_name,
        title=title,
        url=url,
        published_at=published_at,
        vendor=vendor,
        tool_name=tool_name,
        query=query,
        excerpt=excerpt,
    )


def register_unavailable_evidence(
    *,
    tool_name: str,
    vendor: str,
    query: dict[str, Any],
    reason: str,
) -> str | None:
    registry = get_current_evidence_registry()
    if registry is None:
        return None
    return registry.register(
        kind="data_unavailable",
        source_name=vendor or "configured vendors",
        title=f"{tool_name} unavailable",
        url="",
        published_at="",
        vendor=vendor,
        tool_name=tool_name,
        query=query,
        excerpt=reason,
    )


def prefix_with_evidence(text: str, citation_id: str | None, title: str) -> str:
    if not citation_id:
        return text
    return f"## [{citation_id}] {title}\n\n{text}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pytest tests/test_provenance.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/graph/provenance.py tests/test_provenance.py
git commit -m "feat(reports): add provenance context"
```

---

### Task 3: Wire Evidence State Into Graph Runs

**Files:**
- Modify: `tradingagents/agents/utils/agent_states.py`
- Modify: `tradingagents/graph/propagation.py`
- Modify: `tradingagents/graph/trading_graph.py`
- Modify: `api/runner.py`
- Test: `tests/test_provenance.py`
- Test: `tests/webui/test_runner.py`

- [ ] **Step 1: Add failing tests for initial state and WebUI final persistence**

Append to `tests/test_provenance.py`:

```python
from tradingagents.graph.propagation import Propagator


@pytest.mark.unit
def test_initial_state_includes_evidence_items():
    state = Propagator().create_initial_state("600519", "2026-07-06")

    assert state["evidence_items"] == []
```

Append to `tests/webui/test_runner.py`:

```python
def test_runner_persists_evidence_items_from_provenance_context(tmp_path):
    import queue
    import threading

    from api.store import Store
    from api.runner import AnalysisRunner
    from tradingagents.graph.provenance import (
        get_current_evidence_registry,
        register_dataset_evidence,
    )

    class _Graph:
        ticker = "600519"
        config = {}
        _stream_args = {}

        class _Inner:
            def stream(self, init_state, **kwargs):
                register_dataset_evidence(
                    kind="market_data",
                    source_name="AKShare",
                    title="get_stock_data: 600519",
                    vendor="akshare",
                    tool_name="get_stock_data",
                    query={"ticker": "600519"},
                )
                yield {"market_report": "Market improved [S1]."}

        graph = _Inner()

    store = Store(tmp_path / "t.db")
    store.insert_run("r-cite", "600519", "2026-07-06", "stock", {})
    q = queue.Queue()
    runner = AnalysisRunner(store, q, threading.Event(), config={})

    runner.run(
        "r-cite",
        _Graph(),
        {"company_of_interest": "600519", "trade_date": "2026-07-06", "evidence_items": []},
        "Hold",
        None,
    )

    run = store.get_run("r-cite")
    assert run.result["evidence_items"][0]["id"] == "S1"
    assert get_current_evidence_registry() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_provenance.py::test_initial_state_includes_evidence_items tests/webui/test_runner.py::test_runner_persists_evidence_items_from_provenance_context -v
```

Expected: FAIL because `evidence_items` is missing and `AnalysisRunner` does not create a provenance context.

- [ ] **Step 3: Add `evidence_items` to state typing and initial state**

In `tradingagents/agents/utils/agent_states.py`, add this field to `AgentState`:

```python
    evidence_items: Annotated[
        list[dict], "Run-level evidence registry items used for source citations"
    ]
```

In `tradingagents/graph/propagation.py`, add this key to the returned initial state:

```python
            "evidence_items": [],
```

- [ ] **Step 4: Set and clear provenance context in WebUI runner**

In `api/runner.py`, add imports:

```python
from tradingagents.graph.evidence import EvidenceRegistry
from tradingagents.graph.provenance import (
    clear_current_evidence_registry,
    current_evidence_items,
    set_current_evidence_registry,
)
```

Inside `AnalysisRunner.run()`, after run logger setup and before streaming:

```python
        evidence_registry = EvidenceRegistry(init_state.get("evidence_items") or [])
        set_current_evidence_registry(evidence_registry)
```

Before `self._store.complete_run(...)`, ensure `final_state` includes the snapshot:

```python
            if final_state is None:
                final_state = accumulated
            final_state = dict(final_state or {})
            final_state["evidence_items"] = current_evidence_items()
```

In the `finally` block, clear provenance with the logger:

```python
                        clear_current_evidence_registry()
```

- [ ] **Step 5: Set and clear provenance context in direct graph propagation**

In `tradingagents/graph/trading_graph.py`, add imports:

```python
from tradingagents.graph.evidence import EvidenceRegistry
from tradingagents.graph.provenance import (
    clear_current_evidence_registry,
    current_evidence_items,
    set_current_evidence_registry,
)
```

In `TradingAgentsGraph._run_graph()`, after `init_agent_state` is created, use the local state variable:

```python
        evidence_registry = EvidenceRegistry(init_agent_state.get("evidence_items") or [])
        set_current_evidence_registry(evidence_registry)
```

After the final state is available and before assigning `self.curr_state`:

```python
        final_state = dict(final_state or {})
        final_state["evidence_items"] = current_evidence_items()
```

Wrap the graph execution portion of `_run_graph()` in `try/finally` and clear the context in the `finally` block:

```python
        try:
            if self.debug:
                trace = []
                for chunk in self.graph.stream(init_agent_state, **args):
                    if len(chunk["messages"]) == 0:
                        pass
                    else:
                        chunk["messages"][-1].pretty_print()
                        trace.append(chunk)
                final_state = {}
                for chunk in trace:
                    final_state.update(chunk)
            else:
                final_state = self.graph.invoke(init_agent_state, **args)
            final_state = dict(final_state or {})
            final_state["evidence_items"] = current_evidence_items()
        finally:
            clear_current_evidence_registry()
```

Keep any existing run logger cleanup in the same `finally` block.

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest tests/test_provenance.py::test_initial_state_includes_evidence_items tests/webui/test_runner.py::test_runner_persists_evidence_items_from_provenance_context -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tradingagents/agents/utils/agent_states.py tradingagents/graph/propagation.py tradingagents/graph/trading_graph.py api/runner.py tests/test_provenance.py tests/webui/test_runner.py
git commit -m "feat(reports): persist evidence state"
```

---

### Task 4: Render Citation Source Tables in Downloaded Reports

**Files:**
- Modify: `api/reporting.py`
- Modify: `tests/webui/test_routes_analysis.py`

- [ ] **Step 1: Write failing report download tests**

Append to `tests/webui/test_routes_analysis.py`:

```python
def test_report_download_renders_section_and_global_source_tables(client):
    import api.main as main

    store = main.get_store()
    store.insert_run("r-cited", "600519", "2026-07-06", "stock", {})
    store.complete_run(
        "r-cited",
        decision="Hold",
        result={
            "market_report": "量能放大 [S1]。",
            "final_trade_decision": "**Rating**: Hold\n\n等待确认 [S1]。",
            "evidence_items": [
                {
                    "id": "S1",
                    "kind": "market_data",
                    "source_name": "AKShare",
                    "title": "get_stock_data: 600519",
                    "url": "",
                    "published_at": "2026-06-29..2026-07-06",
                    "vendor": "akshare",
                    "tool_name": "get_stock_data",
                    "query": {"ticker": "600519"},
                    "excerpt": "",
                }
            ],
        },
    )

    resp = client.get("/api/analysis/r-cited/report")

    assert resp.status_code == 200
    assert "### 引用来源" in resp.text
    assert "## 全部数据来源" in resp.text
    assert "| [S1] | AKShare | get_stock_data: 600519 | 2026-06-29..2026-07-06 | - |" in resp.text


def test_report_download_without_evidence_keeps_old_behavior(client):
    import api.main as main

    store = main.get_store()
    store.insert_run("r-old", "NVDA", "2024-05-10", "stock", {})
    store.complete_run("r-old", decision="Buy", result={"market_report": "Up"})

    resp = client.get("/api/analysis/r-old/report")

    assert resp.status_code == 200
    assert "Up" in resp.text
    assert "引用来源" not in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/webui/test_routes_analysis.py::test_report_download_renders_section_and_global_source_tables tests/webui/test_routes_analysis.py::test_report_download_without_evidence_keeps_old_behavior -v
```

Expected: first test FAIL because source tables are not rendered.

- [ ] **Step 3: Implement report rendering**

In `api/reporting.py`, add imports:

```python
from tradingagents.graph.evidence import extract_citation_ids, render_source_table
```

Update `build_markdown_report`:

```python
def build_markdown_report(run) -> str:
    title = f"{run.ticker} {run.instrument_name}" if run.instrument_name else run.ticker
    parts = [f"# TradingAgents 分析报告 — {title} ({run.trade_date})\n"]
    if run.decision:
        parts.append(f"**决策: {run.decision}**\n")

    result = run.result or {}
    evidence_items = result.get("evidence_items") or []
    all_cited: list[str] = []
    seen_global: set[str] = set()

    for key, section_title in _REPORT_ORDER:
        content = result.get(key)
        if content:
            parts.append(f"\n## {section_title}\n\n{content}\n")
            citation_ids = extract_citation_ids(content)
            for citation_id in citation_ids:
                if citation_id not in seen_global:
                    seen_global.add(citation_id)
                    all_cited.append(citation_id)
            table = render_source_table(evidence_items, citation_ids, heading="引用来源")
            if table:
                parts.append(f"\n{table}\n")

    global_table = render_source_table(evidence_items, all_cited, heading="全部数据来源")
    if global_table:
        parts.append("\n" + global_table.replace("### 全部数据来源", "## 全部数据来源") + "\n")
    return "\n".join(parts)
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/webui/test_routes_analysis.py::test_report_download_renders_section_and_global_source_tables tests/webui/test_routes_analysis.py::test_report_download_without_evidence_keeps_old_behavior -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/reporting.py tests/webui/test_routes_analysis.py
git commit -m "feat(webui): render report citation sources"
```

---

### Task 5: Register Evidence in Agent-Facing Data Tools

**Files:**
- Modify: `tradingagents/agents/utils/news_data_tools.py`
- Modify: `tradingagents/agents/utils/core_stock_tools.py`
- Modify: `tradingagents/agents/utils/technical_indicators_tools.py`
- Modify: `tradingagents/agents/utils/fundamental_data_tools.py`
- Modify: `tradingagents/agents/utils/market_data_validation_tools.py`
- Test: `tests/test_provenance.py`

- [ ] **Step 1: Add failing tests for tool evidence registration**

Append to `tests/test_provenance.py`:

```python
@pytest.mark.unit
def test_stock_tool_registers_dataset_evidence(monkeypatch):
    from tradingagents.agents.utils.core_stock_tools import get_stock_data
    from tradingagents.graph.evidence import EvidenceRegistry
    from tradingagents.graph.provenance import (
        clear_current_evidence_registry,
        current_evidence_items,
        set_current_evidence_registry,
    )

    monkeypatch.setattr(
        "tradingagents.agents.utils.core_stock_tools.route_to_vendor",
        lambda method, symbol, start_date, end_date: "date,close\n2026-07-06,10\n",
    )
    set_current_evidence_registry(EvidenceRegistry())
    try:
        result = get_stock_data.func("600519", "2026-06-29", "2026-07-06")
        items = current_evidence_items()
    finally:
        clear_current_evidence_registry()

    assert result.startswith("## [S1] get_stock_data: 600519")
    assert items[0]["tool_name"] == "get_stock_data"
    assert items[0]["published_at"] == "2026-06-29..2026-07-06"


@pytest.mark.unit
def test_news_tool_registers_unavailable_evidence(monkeypatch):
    from tradingagents.agents.utils.news_data_tools import get_news
    from tradingagents.graph.evidence import EvidenceRegistry
    from tradingagents.graph.provenance import (
        clear_current_evidence_registry,
        current_evidence_items,
        set_current_evidence_registry,
    )

    monkeypatch.setattr(
        "tradingagents.agents.utils.news_data_tools.route_to_vendor",
        lambda method, ticker, start_date, end_date: "DATA_SOURCE_UNAVAILABLE: blocked",
    )
    set_current_evidence_registry(EvidenceRegistry())
    try:
        result = get_news.func("600519", "2026-06-29", "2026-07-06")
        items = current_evidence_items()
    finally:
        clear_current_evidence_registry()

    assert result.startswith("## [S1] get_news unavailable")
    assert items[0]["kind"] == "data_unavailable"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_provenance.py::test_stock_tool_registers_dataset_evidence tests/test_provenance.py::test_news_tool_registers_unavailable_evidence -v
```

Expected: FAIL because wrappers return raw vendor text.

- [ ] **Step 3: Register evidence in `get_stock_data`**

In `tradingagents/agents/utils/core_stock_tools.py`, import:

```python
from tradingagents.graph.provenance import (
    prefix_with_evidence,
    register_dataset_evidence,
    register_unavailable_evidence,
)
```

Replace the return body in `get_stock_data`:

```python
    result = route_to_vendor("get_stock_data", symbol, start_date, end_date)
    query = {"ticker": symbol, "start_date": start_date, "end_date": end_date}
    if isinstance(result, str) and result.startswith(("NO_DATA_AVAILABLE:", "DATA_SOURCE_", "DATA_SOURCE_DISABLED:")):
        citation_id = register_unavailable_evidence(
            tool_name="get_stock_data",
            vendor="configured vendors",
            query=query,
            reason=result,
        )
        return prefix_with_evidence(result, citation_id, "get_stock_data unavailable")
    citation_id = register_dataset_evidence(
        kind="market_data",
        source_name="configured market data vendor",
        title=f"get_stock_data: {symbol}",
        vendor="configured vendors",
        tool_name="get_stock_data",
        query=query,
        published_at=f"{start_date}..{end_date}",
    )
    return prefix_with_evidence(result, citation_id, f"get_stock_data: {symbol}")
```

- [ ] **Step 4: Register evidence in news tools**

In `tradingagents/agents/utils/news_data_tools.py`, import the same provenance helpers. For `get_news`, replace the final return:

```python
    result = route_to_vendor("get_news", ticker, start_date, end_date)
    query = {"ticker": ticker, "start_date": start_date, "end_date": end_date}
    if isinstance(result, str) and result.startswith(("NO_DATA_AVAILABLE:", "DATA_SOURCE_", "DATA_SOURCE_DISABLED:", "Error fetching news")):
        citation_id = register_unavailable_evidence(
            tool_name="get_news",
            vendor="configured vendors",
            query=query,
            reason=result,
        )
        return prefix_with_evidence(result, citation_id, "get_news unavailable")
    citation_id = register_dataset_evidence(
        kind="news",
        source_name="configured news vendor",
        title=f"get_news: {ticker}",
        vendor="configured vendors",
        tool_name="get_news",
        query=query,
        published_at=f"{start_date}..{end_date}",
    )
    return prefix_with_evidence(result, citation_id, f"get_news: {ticker}")
```

Apply the same pattern to `get_global_news` with query `{"curr_date": curr_date, "look_back_days": look_back_days, "limit": limit}` and title `get_global_news`.

Apply the same pattern to `get_insider_transactions` with query `{"ticker": ticker}` and title `get_insider_transactions: {ticker}`.

- [ ] **Step 5: Register evidence in indicators, fundamentals, and verified snapshot tools**

Use the same helper pattern:

```python
    citation_id = register_dataset_evidence(
        kind="market_data",
        source_name="configured technical indicator vendor",
        title=f"get_indicators: {symbol} {ind}",
        vendor="configured vendors",
        tool_name="get_indicators",
        query={"ticker": symbol, "indicator": ind, "curr_date": curr_date, "look_back_days": look_back_days},
        published_at=f"{look_back_days} days ending {curr_date}",
    )
```

For fundamentals:

```python
    citation_id = register_dataset_evidence(
        kind="fundamentals",
        source_name="configured fundamentals vendor",
        title=f"{tool_name}: {ticker}",
        vendor="configured vendors",
        tool_name=tool_name,
        query={"ticker": ticker, "freq": freq, "curr_date": curr_date},
        published_at=curr_date or "",
    )
```

For verified snapshot:

```python
    citation_id = register_dataset_evidence(
        kind="market_data",
        source_name="verified market snapshot",
        title=f"get_verified_market_snapshot: {symbol}",
        vendor="configured vendors",
        tool_name="get_verified_market_snapshot",
        query={"ticker": symbol, "curr_date": curr_date},
        published_at=curr_date,
    )
```

If any result begins with `NO_DATA_AVAILABLE:`, `DATA_SOURCE_UNAVAILABLE:`, or `DATA_SOURCE_DISABLED:`, register `data_unavailable` and prefix with `"{tool_name} unavailable"`.

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest tests/test_provenance.py::test_stock_tool_registers_dataset_evidence tests/test_provenance.py::test_news_tool_registers_unavailable_evidence -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tradingagents/agents/utils/news_data_tools.py tradingagents/agents/utils/core_stock_tools.py tradingagents/agents/utils/technical_indicators_tools.py tradingagents/agents/utils/fundamental_data_tools.py tradingagents/agents/utils/market_data_validation_tools.py tests/test_provenance.py
git commit -m "feat(reports): register tool evidence"
```

---

### Task 6: Add Citation Prompt Instructions and Evidence Snapshots to Agents

**Files:**
- Modify: `tradingagents/agents/utils/agent_utils.py`
- Modify: `tradingagents/agents/analysts/market_analyst.py`
- Modify: `tradingagents/agents/analysts/news_analyst.py`
- Modify: `tradingagents/agents/analysts/fundamentals_analyst.py`
- Modify: `tradingagents/agents/analysts/sentiment_analyst.py`
- Modify: `tradingagents/agents/researchers/bull_researcher.py`
- Modify: `tradingagents/agents/researchers/bear_researcher.py`
- Modify: `tradingagents/agents/managers/research_manager.py`
- Modify: `tradingagents/agents/trader/trader.py`
- Modify: `tradingagents/agents/risk_mgmt/aggressive_debator.py`
- Modify: `tradingagents/agents/risk_mgmt/conservative_debator.py`
- Modify: `tradingagents/agents/risk_mgmt/neutral_debator.py`
- Modify: `tradingagents/agents/managers/portfolio_manager.py`
- Test: `tests/test_provenance.py`

- [ ] **Step 1: Write failing tests for shared prompt text and state update helper**

Append to `tests/test_provenance.py`:

```python
@pytest.mark.unit
def test_citation_instruction_mentions_no_fake_ids():
    from tradingagents.agents.utils.agent_utils import get_citation_instruction

    instruction = get_citation_instruction()

    assert "[S#]" in instruction
    assert "Do not invent citation ids" in instruction


@pytest.mark.unit
def test_with_evidence_items_adds_current_snapshot():
    from tradingagents.agents.utils.agent_utils import with_evidence_items
    from tradingagents.graph.evidence import EvidenceRegistry
    from tradingagents.graph.provenance import (
        clear_current_evidence_registry,
        register_dataset_evidence,
        set_current_evidence_registry,
    )

    set_current_evidence_registry(EvidenceRegistry())
    try:
        register_dataset_evidence(
            kind="market_data",
            source_name="AKShare",
            title="snapshot",
            vendor="akshare",
            tool_name="get_verified_market_snapshot",
            query={"ticker": "600519"},
        )
        out = with_evidence_items({"market_report": "ok [S1]"})
    finally:
        clear_current_evidence_registry()

    assert out["market_report"] == "ok [S1]"
    assert out["evidence_items"][0]["id"] == "S1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_provenance.py::test_citation_instruction_mentions_no_fake_ids tests/test_provenance.py::test_with_evidence_items_adds_current_snapshot -v
```

Expected: FAIL because helpers do not exist.

- [ ] **Step 3: Add shared helpers**

In `tradingagents/agents/utils/agent_utils.py`, import:

```python
from tradingagents.graph.provenance import current_evidence_items
```

Add:

```python
def get_citation_instruction() -> str:
    return (
        "\n\nCitation rules:\n"
        "- Add one or more existing [S#] citation ids after every key factual claim, "
        "data point, news event, sentiment observation, or source-backed conclusion.\n"
        "- Use only citation ids that appear in tool outputs or upstream reports.\n"
        "- Do not invent citation ids or links.\n"
        "- If no citation id supports a claim, write that no citable source is available.\n"
    )


def with_evidence_items(update: dict) -> dict:
    out = dict(update)
    items = current_evidence_items()
    if items:
        out["evidence_items"] = items
    return out
```

- [ ] **Step 4: Update analyst prompts and returns**

For `market_analyst.py`, `news_analyst.py`, and `fundamentals_analyst.py`:

1. Import `get_citation_instruction` and `with_evidence_items`.
2. Append `+ get_citation_instruction()` to the `system_message`.
3. Replace returns such as:

```python
        return {
            "messages": [result],
            "market_report": report,
        }
```

with:

```python
        return with_evidence_items({
            "messages": [result],
            "market_report": report,
        })
```

Use the correct report key in each file.

- [ ] **Step 5: Update sentiment analyst**

In `tradingagents/agents/analysts/sentiment_analyst.py`:

1. Import `get_citation_instruction` and `with_evidence_items`.
2. Append `get_citation_instruction()` to both domestic and global system-message builders.
3. Wrap the return:

```python
        return with_evidence_items({
            "messages": [AIMessage(content=report_text)],
            "sentiment_report": report_text,
        })
```

- [ ] **Step 6: Update downstream agents**

For each researcher, manager, trader, risk analyst, and portfolio manager module listed in this task:

1. Import `get_citation_instruction` and `with_evidence_items` from `tradingagents.agents.utils.agent_utils`.
2. Add `\n{get_citation_instruction()}` to the prompt string.
3. Wrap the node return dict with `with_evidence_items(...)`.

Example for a node that currently returns `{"investment_plan": plan}`:

```python
        return with_evidence_items({"investment_plan": plan})
```

Example for a debate node that returns debate state:

```python
        return with_evidence_items({
            "investment_debate_state": new_debate_state,
        })
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
pytest tests/test_provenance.py::test_citation_instruction_mentions_no_fake_ids tests/test_provenance.py::test_with_evidence_items_adds_current_snapshot -v
```

Expected: PASS.

- [ ] **Step 8: Run graph smoke tests**

Run:

```bash
pytest tests/webui/test_runner.py tests/test_report_validator_wiring.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add tradingagents/agents tests/test_provenance.py
git commit -m "feat(reports): instruct agents to cite evidence"
```

---

### Task 7: Validate Citations in Report Validator

**Files:**
- Modify: `tradingagents/graph/report_validator.py`
- Test: `tests/test_report_validator.py`

- [ ] **Step 1: Write failing validation test**

Append to `tests/test_report_validator.py`:

```python
@pytest.mark.unit
def test_report_validator_reports_invalid_citations(monkeypatch):
    monkeypatch.setattr(rv, "build_verified_market_snapshot", lambda s, d: "SNAPSHOT")
    llm, _ = _structured_llm(
        invoke_return=CorrectedReport(corrected_text="证据存在 [S2]，非法引用 [S9]。", corrections=[])
    )
    node = rv.create_report_validator(llm, enabled=True)
    out = node(
        _state(
            market_report="证据存在 [S2]，非法引用 [S9]。",
            evidence_items=[
                {
                    "id": "S2",
                    "kind": "news",
                    "source_name": "财联社",
                    "title": "新闻",
                    "url": "",
                    "published_at": "2026-07-06",
                    "vendor": "akshare",
                    "tool_name": "get_news",
                    "query": {},
                    "excerpt": "",
                }
            ],
        )
    )

    assert "无效引用" in out["validation_report"]
    assert "[S9]" in out["validation_report"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_report_validator.py::test_report_validator_reports_invalid_citations -v
```

Expected: FAIL because invalid citation ids are not checked.

- [ ] **Step 3: Add citation validation helper in report validator**

In `tradingagents/graph/report_validator.py`, import:

```python
from tradingagents.graph.evidence import extract_citation_ids
```

Add:

```python
def _citation_warnings(state: dict) -> list[str]:
    evidence_ids = {
        item.get("id")
        for item in state.get("evidence_items", []) or []
        if isinstance(item, dict)
    }
    warnings: list[str] = []
    for key, label in REPORT_FIELDS:
        text = state.get(key) or ""
        cited = extract_citation_ids(text)
        invalid = [cid for cid in cited if cid not in evidence_ids]
        if invalid:
            warnings.append(f"- {label}: 无效引用 " + ", ".join(f"[{cid}]" for cid in invalid))
        if text and evidence_ids and not cited:
            warnings.append(f"- {label}: 未发现来源引用。")
    return warnings
```

At the end of the validator node, before returning, append:

```python
        citation_warnings = _citation_warnings({**state, **updates})
        if citation_warnings:
            validation_lines.append("\n### 引用校验\n" + "\n".join(citation_warnings))
```

Use the existing local variable names in `report_validator.py`; if the file uses a single report string instead of `validation_lines`, append the citation block to that string before assigning `validation_report`.

- [ ] **Step 4: Run focused test**

Run:

```bash
pytest tests/test_report_validator.py::test_report_validator_reports_invalid_citations -v
```

Expected: PASS.

- [ ] **Step 5: Run report validator tests**

Run:

```bash
pytest tests/test_report_validator.py tests/test_report_validator_wiring.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/graph/report_validator.py tests/test_report_validator.py
git commit -m "feat(reports): validate citation ids"
```

---

### Task 8: Final Verification and Changelog

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add changelog entry**

Add an entry under the current unreleased section in `CHANGELOG.md`:

```markdown
- Added run-level evidence tracking and `[S#]` source citations for TradingAgents reports, with markdown source tables on report export.
```

- [ ] **Step 2: Run focused cited-report tests**

Run:

```bash
pytest tests/test_evidence.py tests/test_provenance.py tests/webui/test_routes_analysis.py::test_report_download_renders_section_and_global_source_tables tests/test_report_validator.py::test_report_validator_reports_invalid_citations -v
```

Expected: PASS.

- [ ] **Step 3: Run non-integration test suite**

Run:

```bash
pytest -m "not integration"
```

Expected: PASS. If failures are unrelated to cited reports, record the failing test names and reason in the handoff before continuing.

- [ ] **Step 4: Run lint**

Run:

```bash
ruff check .
```

Expected: PASS.

- [ ] **Step 5: Inspect git diff**

Run:

```bash
git diff --stat HEAD
git diff --check
```

Expected: `git diff --check` exits 0; diff stat only includes cited-report implementation files and tests.

- [ ] **Step 6: Commit final verification and changelog**

```bash
git add CHANGELOG.md
git commit -m "docs: note cited report sources"
```
