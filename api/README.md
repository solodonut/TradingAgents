# TradingAgents WebUI API

FastAPI backend for the conversational analysis assistant.

## Run (dev)

    pip install -e ".[dev]"
    uvicorn api.main:app --reload --port 8000

Frontend (separate terminal):

    cd webui && npm run dev   # http://localhost:3000

## Endpoints

- `GET  /api/config/options` — config card options
- `POST /api/analysis` — start a run, returns `{run_id}` (409 if one is running)
- `GET  /api/analysis/{run_id}/stream` — SSE event stream
- `GET  /api/analysis/{run_id}/report` — download Markdown report
- `GET  /api/history` — list past runs
- `GET  /api/history/{run_id}` — run detail
- `DELETE /api/history/{run_id}` — delete a run

History DB: `~/.tradingagents/webui.db`.
