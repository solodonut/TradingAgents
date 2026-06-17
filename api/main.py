"""FastAPI application entry point for the TradingAgents WebUI."""

import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import config as config_routes
from api.store import Store
from tradingagents.default_config import DEFAULT_CONFIG

try:
    from tradingagents.graph.trading_graph import TradingAgentsGraph
except Exception:  # noqa: BLE001
    TradingAgentsGraph = None

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
app.state.cancellations = {}
app.state.telemetry = {}
app.state.starting_telemetry = None
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


def real_graph_factory(req):
    """Build a TradingAgentsGraph from a request.

    Returns (graph, init_state_with_stream_args, None, None). The init_state we
    return is a tuple-free dict; stream args are attached on the graph instance
    as ``_stream_args`` for the runner to pass through to ``.stream()``.
    decision/final_state are computed by the runner after the stream completes.
    """
    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = req.research_depth
    config["max_risk_discuss_rounds"] = req.research_depth
    config["output_language"] = req.output_language
    if req.llm_provider:
        config["llm_provider"] = req.llm_provider
    if req.deep_think_llm:
        config["deep_think_llm"] = req.deep_think_llm
    if req.quick_think_llm:
        config["quick_think_llm"] = req.quick_think_llm

    telemetry = getattr(app.state, "starting_telemetry", None)
    callbacks = [telemetry.callback_handler()] if telemetry is not None else []

    graph = TradingAgentsGraph(
        selected_analysts=req.analysts, debug=False, config=config, callbacks=callbacks
    )

    past_context = graph.memory_log.get_past_context(req.ticker)
    instrument_context = graph.resolve_instrument_context(req.ticker, req.asset_type)
    init_state = graph.propagator.create_initial_state(
        req.ticker,
        req.trade_date,
        asset_type=req.asset_type,
        past_context=past_context,
        instrument_context=instrument_context,
    )
    # Attach the proper stream args so the runner can pass them through.
    graph._stream_args = graph.propagator.get_graph_args()
    return graph, init_state, None, None


@app.on_event("startup")
def _wire_graph_factory():
    if app.state.graph_factory is None:
        app.state.graph_factory = real_graph_factory
