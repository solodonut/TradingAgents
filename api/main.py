"""FastAPI application entry point for the TradingAgents WebUI."""

import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import config as config_routes
from api.store import Store

DB_PATH = Path.home() / ".tradingagents" / "webui.db"

app = FastAPI(title="TradingAgents WebUI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single-user invariant: only one analysis runs at a time.
app.state.store = None
app.state.run_lock = threading.Lock()


def get_store() -> Store:
    if app.state.store is None:
        app.state.store = Store(DB_PATH)
    return app.state.store


app.include_router(config_routes.router)
