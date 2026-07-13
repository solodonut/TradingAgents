# Disable ETF intraday prefetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop all TradingAgents analysis prefetches from calling `get_etf_intraday`.

**Architecture:** Keep the underlying Tushare function and its diagnostics/vendor registrations intact. Narrow the analysis prefetch category list and fetcher map to news, indicators, and fundamentals; the context builder then receives no intraday quote for new runs.

**Tech Stack:** Python, pytest, FastAPI WebUI pre-run initialization.

---

### Task 1: Remove intraday from the analysis prefetch contract

**Files:**
- Modify: `tests/test_prefetch.py`
- Modify: `tradingagents/dataflows/prefetch.py`

- [x] **Step 1: Write the failing regression test**

```python
def test_prefetch_does_not_call_intraday(monkeypatch):
    monkeypatch.setattr(prefetch, "_fetch_news", lambda t, d: {"text": "news"})
    monkeypatch.setattr(
        prefetch,
        "_fetch_intraday",
        lambda t, d: (_ for _ in ()).throw(AssertionError("intraday must not run")),
        raising=False,
    )
    monkeypatch.setattr(prefetch, "_fetch_indicators", lambda t, d, lb: {"kline": [1]})
    monkeypatch.setattr(prefetch, "_fetch_fundamentals", lambda t, d: {"items": [1]})

    store = FakeStore()
    summary = prefetch.prefetch_snapshot(
        "510300.SS", "2026-07-07", store, config=_cfg(), sleep=lambda s: None
    )

    assert [result.category for result in summary.results] == ["news", "indicators", "fundamentals"]
    assert set(store.rows) == {"news", "indicators", "fundamentals"}
    assert summary.for_context()["quote"] is None
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_prefetch.py::test_prefetch_does_not_call_intraday -v`

Expected: FAIL because the current prefetch contract invokes `_fetch_intraday()`.

- [x] **Step 3: Write the minimal implementation**

```python
_CATEGORIES = ("news", "indicators", "fundamentals")

fetchers = {
    "news": lambda: _fetch_news(ticker, trade_date),
    "indicators": lambda: _fetch_indicators(ticker, trade_date, lookback),
    "fundamentals": lambda: _fetch_fundamentals(ticker, trade_date),
}
```

- [x] **Step 4: Update existing prefetch expectations**

Update tests that treat intraday as a successful or missing analysis category,
so they assert only the remaining three categories and `quote is None`.

- [x] **Step 5: Run focused tests**

Run: `.venv/bin/python -m pytest tests/test_prefetch.py tests/test_prefetch_context.py tests/webui/test_graph_factory.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/dataflows/prefetch.py tests/test_prefetch.py \
  docs/superpowers/specs/2026-07-13-disable-etf-intraday-prefetch-design.md \
  docs/superpowers/plans/2026-07-13-disable-etf-intraday-prefetch.md
git commit -m "fix(etf): disable intraday analysis prefetch"
```
