# Endpoint API Configuration

This document is the reference map for TradingAgents endpoints and data-source
configuration. It covers:

- WebUI/FastAPI HTTP endpoints exposed by `api/`.
- Agent data endpoints routed through `tradingagents.dataflows.interface`.
- External API/MCP sources used or evaluated for China A-share and ETF coverage.

## Runtime HTTP API

The WebUI backend is mounted from `api/main.py` and exposes these FastAPI
routes.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/config/options` | Return selectable model/provider/config options. |
| `POST` | `/api/analysis` | Enqueue one analysis run and start the scheduler. |
| `POST` | `/api/analysis/{run_id}/cancel` | Cancel a running analysis. |
| `GET` | `/api/analysis/{run_id}/status` | Return DB status plus live LLM telemetry. |
| `GET` | `/api/analysis/{run_id}/stream` | Stream analysis events over SSE. |
| `GET` | `/api/analysis/{run_id}/report` | Download a completed run as Markdown. |
| `POST` | `/api/queue` | Enqueue a batch of tickers. |
| `GET` | `/api/queue` | Return the current running/pending queue. |
| `DELETE` | `/api/queue/{run_id}` | Remove one pending queue item. |
| `DELETE` | `/api/queue` | Clear all pending queue items. |
| `PATCH` | `/api/queue/order` | Reorder pending queue items. |
| `GET` | `/api/history` | List historical analysis runs. |
| `GET` | `/api/history/reports.zip` | Download selected or all completed reports as a zip. |
| `GET` | `/api/history/{run_id}` | Return one historical run. |
| `DELETE` | `/api/history/{run_id}` | Delete one historical run. |
| `POST` | `/api/chat/sessions` | Create an advisor chat session. |
| `GET` | `/api/chat/sessions` | List advisor chat sessions. |
| `DELETE` | `/api/chat/sessions` | Bulk-delete advisor chat sessions. |
| `GET` | `/api/chat/sessions/{session_id}` | Return one chat session and its messages. |
| `PATCH` | `/api/chat/sessions/{session_id}` | Rename one chat session. |
| `PUT` | `/api/chat/sessions/{session_id}/reports` | Replace the completed analysis runs bound to a chat session. |
| `DELETE` | `/api/chat/sessions/{session_id}` | Delete one chat session. |
| `POST` | `/api/chat/sessions/{session_id}/portfolio` | Extract portfolio holdings from uploaded images. |
| `PUT` | `/api/chat/sessions/{session_id}/portfolio` | Save manually edited portfolio holdings. |
| `GET` | `/api/chat/sessions/{session_id}/portfolio` | Return saved portfolio holdings. |
| `GET` | `/api/chat/sessions/{session_id}/profile` | Return the advisor profile for a session. |
| `PUT` | `/api/chat/sessions/{session_id}/profile` | Save the advisor profile for a session. |
| `POST` | `/api/chat/sessions/{session_id}/stream` | Stream advisor chat responses over SSE. |
| `GET` | `/api/health/services/stream` | Stream service health probe results over SSE. |
| `GET` | `/api/health/services/{service_id}` | Probe one service health entry. |
| `GET` | `/api/ticker/{code}` | Resolve a ticker/code to a display name. |
| `GET` | `/api/watchlist` | Return the persistent watchlist. |
| `PUT` | `/api/watchlist` | Replace the persistent watchlist. |

## Agent Data Endpoints

All agent-facing data tools route through
`tradingagents/dataflows/interface.py::route_to_vendor()`. The configured value
is an exact ordered vendor chain; the router does not silently fall back to
unconfigured vendors. Use comma-separated chains, for example
`"tushare,akshare"`.

| Endpoint | Category | Current vendor implementations | Default config |
| --- | --- | --- | --- |
| `get_stock_data` | `core_stock_apis` | `alpha_vantage`, `yfinance`, `tushare`, `akshare` | `tushare,akshare` |
| `get_indicators` | `technical_indicators` | `alpha_vantage`, `yfinance`, `tushare`, `akshare` | `tushare,akshare` |
| `get_fundamentals` | `fundamental_data` | `alpha_vantage`, `yfinance`, `tushare`, `akshare` | `tushare,akshare` |
| `get_balance_sheet` | `fundamental_data` | `alpha_vantage`, `yfinance`, `tushare`, `akshare` | `tushare,akshare` |
| `get_cashflow` | `fundamental_data` | `alpha_vantage`, `yfinance`, `tushare`, `akshare` | `tushare,akshare` |
| `get_income_statement` | `fundamental_data` | `alpha_vantage`, `yfinance`, `tushare`, `akshare` | `tushare,akshare` |
| `get_news` | `news_data` | `alpha_vantage`, `yfinance`, `longbridge`, `akshare` | `longbridge,akshare` via `tool_vendors` |
| `get_global_news` | `news_data` | `yfinance`, `alpha_vantage` | `longbridge,akshare` category, but this endpoint has neither implementation |
| `get_insider_transactions` | `news_data` | `alpha_vantage`, `yfinance` | `longbridge,akshare` category, but this endpoint has neither implementation |
| `get_macro_indicators` | `macro_data` | `fred` | `disabled` |
| `get_prediction_markets` | `prediction_markets` | `polymarket` | `disabled` |
| `get_etf_profile` | `etf_data` | `akshare`, `tushare`, `tdx`, `longbridge` | `akshare,tushare,tdx,longbridge` via `tool_vendors` |

### Current Defaults

```python
"data_vendors": {
    "core_stock_apis": "tushare,akshare",
    "technical_indicators": "tushare,akshare",
    "fundamental_data": "tushare,akshare",
    "news_data": "longbridge,akshare",
    "macro_data": "disabled",
    "prediction_markets": "disabled",
},
"tool_vendors": {
    "get_news": "longbridge,akshare",
    "get_etf_profile": "akshare,tushare,tdx,longbridge",
}
```

`akshare_auto_route = True` keeps legacy A-share auto-routing for chains that do
not explicitly include Tushare. Explicit chains containing `tushare` keep their
configured order, so the production default tries Tushare before AKShare for
prices, indicators, and fundamentals. Explicit chains containing `longbridge` or
`tdx` are also left in their configured order, so `get_news` stays
Longbridge-first and `get_etf_profile` stays AKShare-first.

Tool-level `tool_vendors` entries take precedence over category-level
`data_vendors`. That is why `get_news` and `get_etf_profile` have their own
default chains even though `get_news` belongs to `news_data` and ETF profile is
listed under `etf_data`.

## China ETF Profile Sources

`get_etf_profile` is the ETF-specific endpoint used for discount/premium, IOPV,
scale, and holdings. The current default is:

```python
"tool_vendors": {
    "get_etf_profile": "akshare,tushare,tdx,longbridge",
}
```

The order is intentionally AKShare-first because AKShare has the broadest ETF
profile coverage for `159241`-style mainland ETFs: real-time IOPV, discount/
premium, market value, latest shares, and holdings with Chinese names. If
AKShare is unreachable or reports no data, the router falls through to Tushare,
then optional TDX, then optional Longbridge.

Fallback behavior:

- **Tushare** is implemented in code through the TradingAgents-configured
  `TUSHARE_TOKEN`. It returns stable fund basic data, T+1 daily OHLCV, NAV,
  adjustment factors, and quarterly holdings, but not real-time IOPV or direct
  discount/premium fields.
- **TDX** is registered as a runtime fallback placeholder. In this repo it is
  available through MCP during Codex sessions, not as a packaged Python/CLI
  runtime dependency; the code adapter raises `VendorNotConfiguredError` so the
  router can continue.
- **Longbridge** is implemented as an optional CLI adapter. If the `longbridge`
  CLI is installed and authenticated, it can contribute static info and quotes;
  otherwise it cleanly skips to the next vendor.

Because field coverage differs, a future richer `get_etf_profile`
implementation may merge sources field-by-field. The current router remains
first-success: the first vendor that returns a usable profile stops the chain.

| Field | Preferred source | Fallback | Notes |
| --- | --- | --- | --- |
| ETF name, full name, exchange | Tushare `fund_basic` | AKShare, Longbridge static, Tongdaxin MCP | Tushare returns structured `ts_code`, names, exchange/listing fields. |
| Tracking index | Tushare `fund_basic` benchmark | AKShare/news text | Tushare is the cleanest source for index benchmark metadata currently available. |
| Manager, custodian, fee | Tushare `fund_basic` | AKShare | Good static reference data. |
| Latest price | Tongdaxin MCP | AKShare, Tushare paid ETF realtime/day endpoints | Tongdaxin MCP returned current ETF price fields in testing. |
| Change / change percent | Tongdaxin MCP | AKShare, Tushare paid ETF realtime/day endpoints | Snapshot field. |
| Volume, turnover amount | Tongdaxin MCP | AKShare, Tushare paid ETF realtime/day endpoints | Snapshot field. |
| Turnover rate, market value | Tongdaxin MCP | AKShare | Tongdaxin MCP returned turnover and market-value fields. |
| NAV / latest net value | Tushare `fund_nav`, Tongdaxin MCP | AKShare | Tushare returns T+1 NAV for the configured API token. |
| Accumulated NAV | Tongdaxin MCP | AKShare | Returned by Tongdaxin MCP in testing. |
| Premium/discount rate | Tongdaxin MCP | AKShare | Tongdaxin MCP returned `溢价率(%)`; AKShare remains fallback. |
| Fund scale | Tongdaxin MCP | AKShare, Tushare when available | Snapshot/derived field. |
| Fund shares | AKShare | Tongdaxin MCP, Tushare when available | Snapshot/derived field. |
| Subscription/redemption status | Tongdaxin MCP | AKShare | Tongdaxin MCP returned `申赎状态`. |
| IOPV | AKShare | Tushare ETF realtime-reference paid permission | Tongdaxin MCP did not return IOPV in testing. |
| Holdings / top constituents | AKShare for names, Tushare `fund_portfolio` for stable disclosed data | Tongdaxin MCP partial | Tushare returns codes/ratios/market value; AKShare returns names in the current profile output. |
| Creation/redemption basket | Tushare paid ETF permissions if available | AKShare/manual exchange data | Not confirmed in current credentials. |

### Tongdaxin MCP Configuration

Local Codex MCP configuration, with the API key redacted:

```toml
[mcp_servers.tdx]
enabled = true
transport = "streamable_http"
url = "https://mcp.tdx.com.cn:3001/mcp"
http_headers = { "tdx-api-key" = "*****" }
```

The exposed tool is currently:

```text
mcp__tdx.tdx_wenda_quotes
```

This is a natural-language query endpoint, not a fixed-schema REST API. It can
return useful ETF snapshot tables, but headers vary with the question. A code
vendor should ask narrow questions and map returned Chinese headers defensively.

Example tested query shape:

```text
question = "510300 最新价 涨跌幅 成交额 换手率 净值 溢价率 基金规模 基金份额"
range = "JJ"
```

Returned fields included latest NAV, NAV date, accumulated NAV, subscription
status, change percent, volume, turnover amount, market value, premium rate,
price, fund scale, and fund shares.

## News Sources

The current `get_news` code supports:

- `longbridge`: optional Longbridge CLI news adapter.
- `akshare`: East Money A-share company news via `stock_news_em`.
- `alpha_vantage`: overseas/company news.
- `yfinance`: Yahoo Finance news.

For China A-shares and ETFs, the default is:

```python
"tool_vendors": {
    "get_news": "longbridge,akshare",
}
```

Longbridge is first for stability. AKShare remains the fallback for Chinese
East Money coverage. If AKShare returns an `Error fetching news...` string
rather than raising, the router treats that as a vendor failure and continues
the configured chain.

| Source | Recommended role | Coverage | Notes |
| --- | --- | --- | --- |
| Longbridge CLI `news` | Primary stable symbol news | Latest symbol news with title, summary/body, URL | Optional runtime dependency; skipped if CLI is missing or unauthenticated. |
| Tushare `news` / `major_news` | Future paid structured news | Short news, long-form news, multiple media sources | Current configured Tushare token lacks `news` permission in testing; not registered for `get_news`. |
| Tushare `anns_d` | Primary structured announcements | Listed-company announcements with PDF URL | Good fit for A-share factual events. |
| Tushare `idx_anns` | ETF/index-related announcements | Index company announcements | Useful for ETF tracking-index changes. |
| WebSearch | Low-cost supplementary source | Recent news, fund company pages, exchange pages, media reports | Must keep source URLs and date filters; best for recent analysis, not strict historical backtests. |
| AKShare | Chinese fallback | East Money stock news | Free and locally relevant, but upstream scraping can be unstable. |
| Tongdaxin MCP | Not recommended for `get_news` currently | Query attempts returned empty rows or quote-only rows | The exposed `tdx_wenda_quotes` tool did not return structured news/announcement title/content fields in testing. |

## MCP Tools Available In This Environment

The current Codex session has these MCP namespaces relevant to market data:

| Namespace | Role | Useful tools for this project |
| --- | --- | --- |
| `mcp__tdx` | Tongdaxin Wenxiaoda MCP | `tdx_wenda_quotes` for ETF snapshot fields and market/financial natural-language queries. |
| `mcp__tushareMcp` | Tushare MCP | `etf_basic`, `fund_portfolio`, `news`, `major_news`, `anns_d`, `idx_anns`, and many A-share/fund endpoints. |
| `mcp__longbridge` | Longbridge OpenAPI MCP | `quote`, `news`, `news_search`, `constituent`, `invest_relation`; code runtime uses the optional `longbridge` CLI adapter, while MCP remains useful during Codex analysis. |

## Implementation Notes For New Vendors

When adding or extending `tdx`, `tushare`, `longbridge`, or `websearch` code vendors:

1. Register the vendor in `VENDOR_LIST` and `VENDOR_METHODS`.
2. Add category defaults only after the vendor implementation is tested.
3. Preserve the router contract: no fabricated values; return explicit no-data
   sentinels when a source cannot serve a symbol.
4. For `get_etf_profile`, prefer field-level merge over first-success routing.
5. For `get_news`, include title, source, publication time, summary/body, and URL.
6. Keep date-window filtering look-ahead-safe for historical runs.
7. Cache volatile news for about one hour and slower ETF/fund disclosures for
   about one day, matching existing AKShare/Tushare cache behavior.

## Environment And Permission Summary

| Source | Required config | Current status |
| --- | --- | --- |
| AKShare | Python package, direct mainland public-source access | Implemented in code; unstable upstream, proxy bypass and retries exist. |
| Tushare | `TUSHARE_TOKEN`; endpoint-specific paid permissions | Implemented for stock, indicators, fundamentals, and ETF profile fallback. News permission failed in current test. |
| Tongdaxin MCP | `tdx` MCP server with `tdx-api-key` header | MCP available in current Codex session; code has a configured-skip placeholder adapter for ETF profile fallback. |
| WebSearch | Search provider/tooling and source extraction | Not implemented as code vendor; suitable for `get_news` supplement. |
| Longbridge | Longbridge OpenAPI auth / `longbridge` CLI on PATH | MCP available; optional CLI adapter implemented for `get_news` and ETF profile fallback. |
| Alpha Vantage | `ALPHA_VANTAGE_API_KEY` | Implemented for US/global style endpoints. |
| yfinance | Python package/network access | Implemented; not preferred for China-only mode. |
| FRED | FRED API key | Implemented but disabled by default. |
| Polymarket | Network access/API | Implemented but disabled by default. |
