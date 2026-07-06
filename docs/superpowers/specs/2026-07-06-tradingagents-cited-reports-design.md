# TradingAgents Cited Reports Design

## Summary

TradingAgents reports should make their evidence traceable. Every key claim in the full report chain should cite a system-generated source id such as `[S3]`. When the underlying source has a URL, especially news or social messages, the exported report should provide a clickable link in a source table.

The design adds run-level evidence tracking. Data tools register evidence items as they fetch or format data, tools expose those ids to agents, agents cite existing ids in their reports, and report rendering expands the cited ids into per-section and global source tables.

## Goals

- Add citations for key facts, data points, news events, social sentiment claims, macro evidence, fundamentals, and market data.
- Cover the full report chain: analyst reports, research manager, trader, risk debate, portfolio manager, and exported markdown.
- Use `[S#]` source ids in report prose.
- Provide clickable links for sources that expose original message or article URLs.
- Keep non-linkable datasets traceable through vendor, tool, query, ticker, and date range metadata.
- Prevent LLMs from inventing source ids or links.
- Preserve old report downloads that do not have evidence metadata.

## Non-Goals

- First-class clickable citation badges in the WebUI.
- Perfect sentence-level automatic citation insertion after the report is generated.
- Rewriting existing vendor integrations into a shared structured return type in the first pass.
- Guaranteeing URLs for datasets whose providers do not expose stable public pages.

## User-Facing Behavior

Reports include inline source ids:

```markdown
半导体板块政策催化增强，带动相关 ETF 情绪改善 [S3]。
近 7 个交易日成交量放大，短线波动上升 [S8]。
```

Each report section appends a source table for ids used in that section:

```markdown
### 引用来源

| 编号 | 来源 | 标题/数据集 | 日期 | 链接 |
|---|---|---|---|---|
| [S3] | 财联社 | 半导体板块获政策支持 | 2026-07-01 | [打开](https://example.com/news/1) |
| [S8] | AKShare | get_stock_data: 600519 近 7 日 OHLCV | 2026-06-29..2026-07-06 | - |
```

The exported markdown report also appends a global "全部数据来源" table. The real-time WebUI can initially display the same markdown text with `[S#]` ids and source tables, without adding custom UI widgets.

## Architecture

### Evidence Items

Add a run-level `evidence_items: list[dict]` field to the LangGraph state. Keep it plain and serializable so it works with checkpoints, WebUI persistence, and tests.

Each evidence item contains:

- `id`: source id without brackets, for example `S1`.
- `kind`: `news`, `social`, `market_data`, `fundamentals`, `macro`, `prediction_market`, `vendor_dataset`, or `data_unavailable`.
- `source_name`: human-readable source, such as `财联社`, `Yahoo Finance`, `AKShare`, `Tushare`, or `FRED`.
- `title`: article title, message title, dataset label, or unavailable-data label.
- `url`: optional URL from the data provider or parser.
- `published_at`: optional article/message date.
- `vendor`: vendor key such as `akshare`, `yfinance`, `tushare`, or `fred`.
- `tool_name`: tool that produced the evidence, such as `get_news` or `get_stock_data`.
- `query`: display-safe query metadata: ticker, date range, indicator, topic, or series id.
- `excerpt`: short text summary or supporting snippet.

### EvidenceRegistry Helper

Add an `EvidenceRegistry` helper around the `evidence_items` list. It should:

- Allocate ids monotonically as `S1`, `S2`, `S3`.
- Avoid id generation by the LLM.
- Optionally deduplicate exact source records by stable key, such as `(kind, source_name, title, url, tool_name, query)`.
- Serialize back to `list[dict]`.
- Render source tables from a set of cited ids.
- Scan markdown for source ids with a strict pattern such as `\[S\d+\]`.

The helper is a convenience layer only. The graph state remains a plain list.

### Runtime Provenance Context

LangChain tools do not naturally mutate `AgentState`, so evidence registration should not depend on passing the state object into every tool. Instead, use a run-scoped provenance context, similar to the existing run logger context:

- Run start creates a current evidence registry for the active thread/run.
- Tool wrappers and sentiment prefetch helpers register evidence through that current registry.
- Analyst and manager nodes include the current registry snapshot in their returned state update as `evidence_items`.
- Report rendering reads `evidence_items` from the final persisted result.

This keeps tool signatures stable while still making evidence available in the graph state and WebUI store.

## Data Flow

### Run Initialization

Initialize `evidence_items` as an empty list in the initial `AgentState` and initialize the run-scoped provenance context before graph execution. Existing code paths that do not provide the field should treat it as an empty list.

### Tool Registration

`route_to_vendor()` should continue to own vendor routing and fallback. Evidence registration should happen near the agent-facing tool wrappers or formatting helpers, where tool name, vendor choice, and formatted data are available.

News-like tools register article/message-level evidence:

- `get_news()`
- `get_global_news()`
- sentiment prefetch sources such as StockTwits and Reddit

Dataset-like tools register one evidence item per query result:

- `get_stock_data()`
- `get_indicators()`
- `get_verified_market_snapshot()`
- `get_fundamentals()`
- `get_balance_sheet()`
- `get_cashflow()`
- `get_income_statement()`
- `get_macro_indicators()`
- `get_prediction_markets()`
- `get_etf_profile()`

Unavailable, disabled, and no-data sentinels should also be represented as `data_unavailable` evidence so agents can cite data limits honestly.

### Tool Output

Agent-facing tool text should include assigned source ids:

```markdown
### [S3] 半导体板块获政策支持 (source: 财联社)
Date: 2026-07-01
Link: https://example.com/news/1
Summary: ...

## [S8] OHLCV 数据集
Source: AKShare
Query: 600519, 2026-06-29..2026-07-06
```

This lets agents cite ids that the system already created. Agents should not need to compose URLs or metadata themselves.

### Agent Prompts

Add a shared citation instruction to analysts, researchers, trader, risk analysts, and portfolio manager prompts:

- Cite one or more existing `[S#]` ids after each key factual claim, data point, news event, or source-backed conclusion.
- Reuse ids from upstream reports when summarizing or debating upstream evidence.
- Do not invent ids.
- If a claim has no available source id, say that no citable source is available instead of fabricating a citation.

Downstream agents should be able to cite source ids carried in prior reports. They do not need direct access to every raw vendor record.

### Report Rendering

`api/reporting.py::build_markdown_report()` should:

- Read `evidence_items` from the run result.
- Scan each section for cited ids.
- Append a per-section "引用来源" table for valid cited ids.
- Ignore or separately flag invalid ids rather than rendering fake links.
- Append a global "全部数据来源" table at the end.
- Preserve old reports that have no `evidence_items`.

## Validation and Error Handling

Add a citation validation helper that checks:

- Valid cited ids exist in `evidence_items`.
- Invalid ids are reported in `validation_report`.
- Sections with few or no citations are reported as citation coverage warnings.

The validator should not automatically rewrite analysis in the first version. It should surface citation problems so prompt tuning and targeted fixes can improve coverage without mutating model opinions.

If evidence registration fails, analysis should continue. The system should log provenance failure and, where useful, add a `DATA_SOURCE_PROVENANCE_UNAVAILABLE` note. Report generation should still work and should mention incomplete source tracking in `validation_report`.

## Security and Privacy

Evidence metadata must not store API keys, auth headers, cookies, or full raw request objects. `query` should contain only display-safe values such as ticker, date range, indicator, series id, topic, and vendor.

URLs should come from data providers, parsers, or deterministic URL builders. They should not be accepted from LLM prose as authoritative metadata.

## Backward Compatibility

Historical runs without `evidence_items` should still download normally. The renderer may omit source tables or add a short note:

```text
本报告生成时尚未启用结构化来源追踪。
```

Existing tests that use fake graph results should not need full evidence data unless they assert citation rendering.

## Testing Plan

- Unit test `EvidenceRegistry` id allocation, deduplication, serialization, citation scanning, and source table rendering.
- Unit test news source parsing for AKShare/YFinance-style formatted markdown, preserving title, source, date, and link.
- Unit test dataset evidence for market data, indicators, fundamentals, and macro tools.
- Unit test invalid citation detection.
- API/reporting test that a run with `evidence_items` exports per-section source tables and a global source table.
- Regression test that a run without `evidence_items` still exports successfully.
- Run `pytest -m "not integration"`.
- Run `ruff check .`.

## Implementation Notes

The first implementation should be surgical:

1. Add evidence data structures and rendering helpers.
2. Wire evidence into initial graph state and API report rendering.
3. Register evidence for the most important existing sources: news, sentiment prefetch, verified market snapshot, stock data, indicators, and fundamentals.
4. Add shared prompt instructions.
5. Add validation and tests.

After the first pass, frontend citation badges and richer per-provider structured returns can be added incrementally.
