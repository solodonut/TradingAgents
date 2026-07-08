# Tushare ETF News Aggregation Design

## Goal

Add an ETF-specific news tool that uses Tushare as the primary news source and gives
ETF analysis the right news context: fund-level news, index or theme news, and news
for the ETF's largest disclosed holdings.

The first version should cover mainland China listed ETFs and funds. It must not
change the behavior of the existing `get_news(ticker, start_date, end_date)` tool for
individual stocks.

## Background

The current news path is stock-centric. `get_news` is a LangChain tool that routes
through `route_to_vendor("get_news", ...)`. In the default China-only setup,
`tool_vendors["get_news"]` is `tushare,akshare,eastmoney`, and the news analyst only
receives `get_news`.

That works for single stocks, but ETF analysis needs different context. ETF price and
NAV are driven by a basket and its tracked index or theme. The existing ETF profile
tool already exposes fund scale, discount/premium, IOPV, and top holdings. The news
layer should use that structure instead of asking the LLM to manually call `get_news`
for an arbitrary list of tickers.

## Approved Approach

Create a new tool:

```python
get_etf_news(symbol: str, start_date: str, end_date: str) -> str
```

This tool is separate from `get_news`. It handles ETF/fund symbols only. The existing
`get_news` path remains the single-symbol company news tool.

The news analyst should receive both tools in China-only mode:

```python
[get_news, get_etf_news]
```

The prompt should instruct the analyst to use `get_etf_news` first for ETF/fund
symbols, and `get_news` for individual stocks.

## Output Shape

`get_etf_news` returns Markdown with fixed sections:

```markdown
# ETF News for 510300.SS, from 2026-07-01 to 2026-07-08

## ETF / Fund-Level News
...

## Index / Theme News
...

## Top Holdings News
### 600519.SS 贵州茅台, weight 5.2%
...

## Coverage Notes
- Holdings source: Tushare fund_portfolio, latest disclosed quarter.
- News source: Tushare first.
- Missing sections: none.
```

Every section may independently degrade. A failure in one holding, one source, or one
section must not fail the whole tool.

## Data Flow

```text
get_etf_news(symbol, start_date, end_date)
  -> validate symbol is mainland ETF/fund
  -> fetch ETF/fund basics and latest disclosed holdings
  -> fetch ETF/fund-level news
  -> derive index/theme query terms
  -> fetch index/theme news
  -> fetch news for top holdings
  -> dedupe and render Markdown
```

### Holdings

Use Tushare first:

- `fund_portfolio(ts_code=<ETF ts_code>)`
- Sort and limit to the top holdings by disclosed weight when weight is available.
- Default to the first rows returned by Tushare if the vendor already orders them and
  weight parsing is unavailable.

Fallback:

- If Tushare holdings are unavailable, use the existing AKShare ETF profile/holding
  path only to obtain the holding list.
- News fetching remains Tushare-first.

If no holdings are available, the tool still returns ETF/fund-level and index/theme
news, with the holdings section marked unavailable.

### ETF / Fund-Level News

Fetch news for the ETF/fund symbol itself through the Tushare implementation. This
captures fund announcements, product news, issuer updates, and exchange/regulatory
items when available.

### Index / Theme News

Do not build a full index constituent database in the first version.

Derive search terms from available ETF metadata:

- fund name
- benchmark or tracked index fields when present in Tushare fund basic data
- common ETF-name patterns such as `沪深300`, `中证A500`, `科创50`, `创业板`,
  `半导体`, `新能源`, and similar theme words embedded in the fund name

If no clean benchmark or theme can be derived, use the fund name as the theme query.

### Top Holdings News

Fetch stock news for the top holdings only:

- Default top holdings count: 5
- Default max articles per holding: 3
- Use existing Tushare stock-news behavior, including company announcements and
  keyword-filtered flash news.

Each holding is rendered under its own heading with stock code, stock name, and weight
when available.

## Configuration

Add these defaults to `DEFAULT_CONFIG`:

```python
"etf_news_top_holdings": 5,
"etf_news_per_holding_limit": 3,
"etf_news_theme_limit": 5,
```

The tool should also reuse the existing `news_article_limit` where appropriate, but
ETF-specific limits win for ETF aggregation. This keeps the result compact enough for
agent prompts.

## Routing And Integration

Add a Tushare dataflow module:

```text
tradingagents/dataflows/tushare_etf_news.py
```

Register it in `tradingagents/dataflows/interface.py`:

```python
VENDOR_METHODS["get_etf_news"] = {
    "tushare": get_tushare_etf_news,
}
```

Add the LangChain tool wrapper in:

```text
tradingagents/agents/utils/news_data_tools.py
```

Export it through:

- `tradingagents/agents/utils/agent_utils.py`
- `tradingagents/advisor/tools.py`, if the advisor chatbot should expose it

Update the news analyst:

- China-only tools become `[get_news, get_etf_news]`.
- The prompt says ETF/fund symbols should use `get_etf_news`; stock symbols should
  use `get_news`.

Update `TradingAgentsGraph._create_tool_nodes()` so the `news` tool node can execute
`get_etf_news` in China-only mode.

## Error Handling

Use the existing project style:

- Vendor functions raise `NoMarketDataError` for unsupported symbols or no usable
  market data.
- Tool wrappers register unavailable evidence for sentinel strings.
- Network/source errors degrade to explicit unavailable text when possible.

Section-level behavior:

- ETF validation failure: return `NO_DATA_AVAILABLE` through normal router handling.
- ETF/fund-level news failure: render that section as unavailable.
- Index/theme query failure: render that section as unavailable.
- One holding news failure: render unavailable for that holding and continue.
- All sections empty: return a clear no-news message, not a blank report.

The report must explicitly state that holdings are based on the latest disclosed
quarter, not real-time positions.

## Look-Ahead Safety

All news must remain inside `[start_date, end_date]`.

The implementation should reuse the existing Tushare news date-window behavior where
possible. Any new index/theme filtering must apply the same date-window rule. News
published after `end_date` must not appear in historical analysis.

## Noise Control

Defaults:

- ETF/fund-level news: max 5 articles
- Index/theme news: max 5 articles
- Top holdings: max 5 holdings
- Per holding: max 3 articles

Deduplicate by normalized title across sections. If the same headline appears under
ETF/theme/holding sections, keep the first occurrence and omit later duplicates.

## Tests

Add unit tests for:

- ETF holdings available: report includes ETF/fund-level, index/theme, and top holding
  sections.
- Holdings unavailable: report still includes ETF/fund-level and index/theme sections,
  and marks holdings unavailable.
- One holding news path fails: other holdings still render.
- Date-window filtering: news after `end_date` is excluded.
- Noise limits: max 5 holdings, max 3 articles per holding, max 5 theme articles.
- Deduplication: repeated titles appear only once.
- China-only tools: news analyst binds both `get_news` and `get_etf_news`.
- Router registration: `route_to_vendor("get_etf_news", ...)` dispatches to Tushare.

Default `pytest` must remain safe with placeholder API keys and no external service.
Tests should mock Tushare client calls.

## Non-Goals

The first version will not:

- Parse full index constituent lists.
- Infer real-time ETF holdings.
- Let the LLM decide how many holdings to fetch.
- Change existing `get_news` behavior for stocks.
- Add overseas news vendors.
- Build a new UI.

## Acceptance Criteria

- ETF news analysis can call one tool and receive a compact, structured ETF news
  package.
- The result includes ETF/fund-level, index/theme, and top holdings sections when
  data is available.
- Missing holdings or partial news failures do not crash the analysis.
- Historical runs do not include future news.
- Existing stock `get_news` behavior and tests continue to pass.
