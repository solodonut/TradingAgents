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
app.state.queues = {}
app.state.graph_factory = None  # set by real_graph_factory at startup; tests inject their own


def get_store() -> Store:
    if app.state.store is None:
        app.state.store = Store(DB_PATH)
    return app.state.store


app.include_router(config_routes.router)

from api.routes import history as history_routes  # noqa: E402

app.include_router(history_routes.router)

from api.routes import analysis as analysis_routes  # noqa: E402

app.include_router(analysis_routes.router)
