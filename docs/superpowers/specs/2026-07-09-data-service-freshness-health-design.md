# Data Service Freshness Health Design

## Goal

Improve WebUI service health checks for data vendors so they verify both reachability and whether the vendor can return today's latest data. A vendor that is reachable but has not updated to today's data should show a warning, not a full outage.

## Scope

- Extend data-service health checks in `api/service_health.py`.
- Preserve the existing streaming and single-service health endpoints.
- Add a `warning` health status for stale-but-reachable data services.
- Keep disabled services, missing credentials, and connectivity failures on their current paths.
- Keep tests mocked; health-check tests must not require real API keys or consume live vendor quota.

## Non-Goals

- Do not change agent data routing or analysis behavior.
- Do not add freshness checks to services where "today's latest data" is not a clear contract, such as Eastmoney search news and Polymarket market listings.
- Do not use cached dataflow calls for health freshness checks, because cached results could hide an upstream update problem.
- Do not broaden this into a general data-quality scoring system.

## Status Semantics

`ServiceHealthStatus` gains one new value:

- `ok`: service is enabled, reachable, and freshness validation passed when applicable.
- `warning`: service is enabled and reachable, but its latest data date is not today's date.
- `error`: service is enabled but missing credentials, unreachable, returning invalid data, or the freshness probe failed.
- `disabled`: service is not enabled by current configuration.
- `checking`: transient frontend state while a probe is running.

Frontend traffic-light priority should be:

1. `error` -> red
2. `warning` -> yellow
3. `checking` -> yellow/loading
4. `ok` -> green
5. `disabled` only -> muted

The summary should include `warning` counts so a stale data source is visible without being conflated with a hard outage.

## Backend Design

Keep `_DATA_SERVICES` as the service registry, and add optional freshness metadata for vendors that support a lightweight date-bearing probe.

For each enabled data service:

1. Check required environment variables.
2. Run the existing reachability probe.
3. If reachability fails, emit `error` and do not run freshness validation.
4. If the service has no freshness probe, emit the existing reachability result.
5. If the service has a freshness probe, fetch one small sample and parse the newest data date.
6. Compare that date to the service-side current date.
7. Emit:
   - `ok` with a message such as `Reachable; latest daily data is 2026-07-09`.
   - `warning` with a message such as `Reachable, but latest daily data is 2026-07-08; expected 2026-07-09`.
   - `error` if the freshness endpoint errors, returns no rows, or cannot be parsed.

The first implementation should cover:

- `tushare`: validate a lightweight daily market data endpoint for a stable mainland sample symbol.
- `akshare`: validate a lightweight A-share daily market sample.
- `yfinance`: validate a daily sample for a stable US symbol.
- `alpha_vantage`: validate the latest quote or daily time series date for a stable US symbol.
- `fred`: validate the latest observation date.

Eastmoney direct news search and Polymarket remain reachability-only because the current health check should not invent a misleading "today's price data" interpretation for them.

## Frontend Design

Update the existing WebUI health types and component only where needed:

- Add `warning` to `ServiceHealthStatus`.
- Add a warning label such as `警告`.
- Render warning rows in amber/yellow with an appropriate icon.
- Include warning counts in the summary line.
- Treat warning as attention-worthy in the collapsed traffic light, but less severe than error.

The existing `message` field continues to carry freshness details, so no new response field is required.

## Error Handling

- Missing API keys remain `error` with the existing credential message.
- Connectivity failures remain `error`.
- Freshness probe network/API failures are `error`, because the service may be reachable at a generic endpoint but unable to serve the actual data needed by the app.
- Reachable but stale data is `warning`.
- Disabled services remain `disabled`.

Messages must not include API keys or request tokens.

## Testing

Backend tests in `tests/webui/test_routes_health.py` should cover:

- Tushare enabled with a token, reachable, and freshness returns today's date -> `ok`.
- Tushare enabled with a token, reachable, and freshness returns yesterday's date -> `warning`.
- Tushare freshness probe failure or unparsable response -> `error`.
- Tushare reachability failure does not run the freshness probe.
- Missing Tushare token remains `error`.
- Disabled data services remain `disabled`.
- Summary counts include `warning`.

Frontend tests should cover:

- `warning` sorts and displays distinctly from `ok`, `error`, and `disabled`.
- The panel summary includes warning counts.
- The collapsed traffic light shows warning when there are no errors.

## Verification

- Run focused backend health route tests.
- Run focused frontend service-health tests.
- If practical, run the broader WebUI test subset after implementation.
