# WebUI Service Health Design

## Goal

Show a visible remote-service health check in the WebUI on first load, after analysis failures, and on manual request.

## Scope

- LLM health uses the existing model health checker so configured deep/quick model slots are checked consistently with startup behavior.
- Data health covers the known remote data services: AKShare/Eastmoney, Yahoo Finance, Alpha Vantage, FRED, and Polymarket.
- Disabled services appear as disabled instead of failed.
- The check is best-effort and never blocks app startup or crashes the API.

## Architecture

- Add a focused backend module, `api/service_health.py`, that yields service status events.
- Add `api/routes/health.py` with a streaming endpoint for visible progress.
- Add frontend types/API helpers and a compact `ServiceHealthPanel` component.
- Wire `webui/app/page.tsx` to run checks on first load, after analysis error events, and from a manual button.

## Testing

- Backend route tests patch the probe functions to avoid real network/API calls.
- Frontend verification uses TypeScript/lint/build checks after implementation.
