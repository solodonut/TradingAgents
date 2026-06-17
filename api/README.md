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
- `POST /api/analysis/{run_id}/cancel` — stop a running analysis
- `GET  /api/analysis/{run_id}/status` — inspect in-memory runtime telemetry for a run
- `GET  /api/analysis/{run_id}/stream` — SSE event stream
- `GET  /api/analysis/{run_id}/report` — download Markdown report
- `GET  /api/history` — list past runs
- `GET  /api/history/{run_id}` — run detail
- `DELETE /api/history/{run_id}` — delete a run
- `POST   /api/chat/sessions` — create a chat session (optional `run_id`)
- `GET    /api/chat/sessions` — list chat sessions
- `GET    /api/chat/sessions/{id}` — session detail + messages
- `DELETE /api/chat/sessions/{id}` — delete a chat session
- `POST   /api/chat/sessions/{id}/portfolio` — extract holdings from a screenshot
- `PUT    /api/chat/sessions/{id}/portfolio` — overwrite holdings (manual)
- `GET    /api/chat/sessions/{id}/portfolio` — read current holdings
- `POST   /api/chat/sessions/{id}/stream` — SSE chat (token / tool_call / done / error)

History DB: `~/.tradingagents/webui.db`.
