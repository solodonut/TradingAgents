# Tushare Primary, AKShare Fallback Design

## Context

The project currently uses AKShare as the default China data source for price,
technical, fundamental, and news tools. Recent history shows AKShare/East Money
connectivity is the weak point, while the WebUI and dataflow layer already have
explicit vendor routing, service health checks, and fallback semantics.

The user has purchased the Tushare Pro 500 yuan/year tier and has placed the
token in `.env` as `TUSHARE_TOKEN`. The goal is to make Tushare the primary
source where that tier can reliably cover the data, while keeping AKShare as a
supplement for fields Tushare does not cover at this tier or for temporary
Tushare failures.

## Goals

- Add Tushare as a first-class data vendor under `tradingagents/dataflows/`.
- Make Tushare the default primary source for China price, technical, and
  fundamental data, with AKShare as ordered fallback.
- Preserve the existing agent-facing contract: agents call
  `route_to_vendor()` only, and vendor failures become explicit no-data,
  unavailable, not-configured, or rate-limit signals.
- Cover as much of the existing AKShare behavior as practical, without
  pretending that Tushare 500 yuan/year includes realtime ETF references,
  realtime order-book fields, IOPV/discount, or paid news permissions.
- Keep tests fully mocked. Unit tests must not require a real Tushare token or
  consume user quota.

## Non-Goals

- Do not remove AKShare.
- Do not call Tushare directly from analyst, trader, graph, or WebUI business
  logic.
- Do not write the user's token into code, tests, logs, reports, or commits.
- Do not implement Tushare news as the default source, because Tushare news is a
  separate paid permission outside the 500 yuan/year points tier.
- Do not force realtime-only AKShare fields into Tushare reports when Tushare
  cannot provide them under the purchased tier.

## Architecture

Add Tushare modules alongside the existing AKShare modules:

- `tradingagents/dataflows/tushare_utils.py`
- `tradingagents/dataflows/tushare_stock.py`
- `tradingagents/dataflows/tushare_indicator.py`
- `tradingagents/dataflows/tushare_fundamentals.py`

Register Tushare in `tradingagents/dataflows/interface.py`:

- Add `tushare` to `VENDOR_LIST`.
- Add Tushare implementations for:
  - `get_stock_data`
  - `get_indicators`
  - `get_fundamentals`
  - `get_balance_sheet`
  - `get_cashflow`
  - `get_income_statement`

Default vendor configuration becomes:

```python
"data_vendors": {
    "core_stock_apis": "tushare,akshare",
    "technical_indicators": "tushare,akshare",
    "fundamental_data": "tushare,akshare",
    "news_data": "akshare",
    "macro_data": "disabled",
    "prediction_markets": "disabled",
}
```

The existing router treats the configured value as an ordered chain, so Tushare
success stops the chain, while Tushare not-configured, rate-limited, no-data, or
failed calls can fall through to AKShare.

`akshare_auto_route` should be revised so it does not move AKShare ahead of an
explicit Tushare chain for China symbols. The intended behavior for mainland
tickers is:

- If the configured chain includes `tushare,akshare`, keep that order.
- If the configured chain does not include Tushare and `akshare_auto_route` is
  enabled, retain the existing AKShare-first behavior.

## Data Coverage

### Core Price Data

Tushare should serve both mainland ETFs/funds and A shares:

- ETFs/funds: use `fund_daily`.
- A shares: use `daily`.

Both paths normalize to the existing CSV-with-header contract:

- `Date`
- `Open`
- `High`
- `Low`
- `Close`
- `Volume`
- `Amount`

The same stale-data guard used by AKShare and yfinance should apply. If Tushare
returns no usable rows or stale rows, raise `NoMarketDataError` so AKShare can
serve the fallback.

### Technical Indicators

Tushare should not introduce a new indicator source. Instead, it should load
Tushare OHLCV, normalize it into the same shape used by AKShare/yfinance, then
compute indicators locally with `stockstats`.

This keeps indicator semantics consistent across vendors for:

- SMA/EMA
- MACD
- RSI
- Bollinger Bands
- ATR
- VWMA
- MFI

### ETF and Fund Fundamentals

For mainland ETF/fund symbols, Tushare should provide a structured fund report
using the 500 yuan/year eligible regular data where available:

- fund basic data
- daily fund price/NAV fields where available
- adjustment factors from `fund_adj`
- portfolio/holding data from `fund_portfolio`

The report should clearly state `(Tushare Pro)` as the source. If a sub-section
is unavailable, omit that section or state it is unavailable; do not invent a
spot snapshot or realtime IOPV.

ETF/fund balance sheet, income statement, and cash-flow tools remain structured
`not_applicable` responses, matching current AKShare behavior.

### A Share Fundamentals

For A shares, Tushare should cover the available regular-data fundamentals and
financial statement surfaces under the user's tier:

- company/basic profile data
- balance sheet
- income statement
- cash-flow statement
- key financial indicators where available

Statement data must be filtered on or before `curr_date` to avoid look-ahead
bias, matching the current AKShare implementation.

### News and Realtime Supplements

Keep `news_data` on AKShare by default. AKShare also remains the supplement for:

- ETF realtime spot snapshots
- realtime order-book fields
- IOPV and discount/premium style realtime references
- East Money style individual-stock/ETF news
- any Tushare interface requiring a separate paid permission not included in
  the 500 yuan/year tier

## Token and Error Handling

`tushare_utils.py` should provide the shared Tushare client setup:

- Read `TUSHARE_TOKEN` from the environment.
- If missing, raise `VendorNotConfiguredError`.
- Initialize the Tushare Pro client lazily.
- Never log the token.

Tushare responses should map into existing project errors:

- Missing token or invalid token: `VendorNotConfiguredError`
- Permission denied or quota/rate-limit response: `VendorRateLimitError` when
  retrying another vendor is reasonable
- Empty data for the requested symbol/date: `NoMarketDataError`
- Network failures: let the router classify them consistently with other
  vendors, or wrap only if needed to preserve fallback behavior

## Caching

Use the existing cache-directory pattern and vendor-specific cache namespace.

Suggested TTLs:

- Price data: 6 hours
- Technical OHLCV base data: reuse price cache when practical
- ETF/fund holdings, adjustment factors, financial statements: 24 hours

Cache keys must include symbol, date window, endpoint intent, and any adjustment
mode. Cache values must not contain token material.

## WebUI and Configuration

Update `.env.example`:

```bash
# Tushare Pro token. Used for mainland China market data when configured.
#TUSHARE_TOKEN=
```

Update service health:

- Add `Tushare Pro` to `api/service_health.py`.
- If Tushare is enabled but `TUSHARE_TOKEN` is absent, report a configuration
  error.
- If token exists, probe a lightweight endpoint such as trade calendar or one
  small daily-data request.
- Keep AKShare health checks because AKShare remains the fallback and supplement.

Reports should identify source names in headers, for example:

- `(Tushare Pro)`
- `(AKShare)`

When AKShare is used after Tushare fails, the router logs should make that
fallback visible.

## Testing

All tests use mocks and do not require real Tushare network access.

Required coverage:

- Default China config uses `tushare,akshare` for price, technical, and
  fundamentals, while news remains `akshare`.
- Tushare is registered in `VENDOR_LIST` and `VENDOR_METHODS`.
- Tushare success prevents AKShare from being called.
- Missing Tushare token falls back to AKShare.
- Tushare no-data, rate-limit, and permission-like failures fall back correctly.
- ETF/fund daily data normalizes to the existing OHLCV/Amount shape.
- Tushare indicators use Tushare OHLCV plus local `stockstats`.
- ETF/fund fundamentals include basic/holding/adjustment sections when mocked
  data exists, and do not fabricate realtime fields.
- ETF/fund financial statements return not-applicable responses.
- A-share statements are filtered by `curr_date`.
- WebUI health reports Tushare as disabled/error/ok as appropriate.

Suggested validation commands:

```bash
pytest tests/test_vendor_routing.py tests/test_china_only_data_sources.py
pytest tests/webui/test_routes_health.py
ruff check tradingagents/dataflows api/service_health.py tests
```

## Dependency

If the Tushare SDK is not already present, add `tushare` to `pyproject.toml` and
refresh `uv.lock` with `uv lock`.

## Rollout

After implementation, the default local behavior should be:

1. User sets `TUSHARE_TOKEN` in `.env`.
2. China price, technical, and fundamental calls try Tushare first.
3. AKShare remains available for fallback and supplemental news/realtime fields.
4. If Tushare is not configured, analysis still works through AKShare with a
   visible not-configured log entry.
