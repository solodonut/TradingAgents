"""FastAPI application entry point for the TradingAgents WebUI."""

import logging
import os
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import config as config_routes
from api.startup_cache import StartupCacheClearer
from api.store import Store
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.health_check import check_and_select

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
app.state.chat_llm_factory = None  # set at startup; tests inject their own
app.state.scheduler = None  # QueueScheduler, created at startup; tests reset to None
app.state.startup_cache_clearer = None  # StartupCacheClearer, created at startup
app.state.model_health = None  # set by the startup health check; tests may inject

logger = logging.getLogger(__name__)


def _startup_model_check_enabled() -> bool:
    return os.getenv("TRADINGAGENTS_STARTUP_MODEL_CHECK", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _run_model_health_check() -> None:
    """Probe configured models, write working ones back to DEFAULT_CONFIG.

    Never raises: a failing or buggy health check must not block startup.
    """
    try:
        report = check_and_select(DEFAULT_CONFIG)
    except Exception:  # noqa: BLE001 - health check must never crash startup
        logger.exception("model-health: health check failed; keeping configured models")
        return

    for slot, slot_report in report.slots.items():
        DEFAULT_CONFIG[slot] = slot_report.selected
        for candidate in slot_report.candidates:
            logger.info(
                "model-health %s candidate=%s ok=%s latency=%dms%s",
                slot,
                candidate.model,
                candidate.ok,
                candidate.latency_ms,
                f" error={candidate.error}" if candidate.error else "",
            )
        if slot_report.configured != slot_report.selected:
            logger.warning(
                "model-health %s switched %s -> %s",
                slot,
                slot_report.configured,
                slot_report.selected,
            )

    app.state.model_health = report

    if report.any_failed:
        failed = [slot for slot, sr in report.slots.items() if sr.all_failed]
        logger.error(
            "model-health: no working model for slots %s on provider %s; keeping configured values",
            failed,
            report.provider,
        )


def get_store() -> Store:
    if app.state.store is None:
        app.state.store = Store(DB_PATH)
    return app.state.store


app.include_router(config_routes.router)

from api.routes import history as history_routes  # noqa: E402

app.include_router(history_routes.router)

from api.routes import analysis as analysis_routes  # noqa: E402

app.include_router(analysis_routes.router)

from api.routes import chat as chat_routes  # noqa: E402

app.include_router(chat_routes.router)

from api.routes import queue as queue_routes  # noqa: E402

app.include_router(queue_routes.router)

from api.routes import health as health_routes  # noqa: E402

app.include_router(health_routes.router)

from api.routes import startup_cache as startup_cache_routes  # noqa: E402

app.include_router(startup_cache_routes.router)

from api.routes import ticker as ticker_routes  # noqa: E402

app.include_router(ticker_routes.router)

from api.routes import watchlist as watchlist_routes  # noqa: E402

app.include_router(watchlist_routes.router)


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

    # Resolve the human-readable name once for the history list (cache hit after
    # resolve_instrument_context above; no extra network). Best-effort: None if unresolved.
    from tradingagents.agents.utils.agent_utils import resolve_instrument_identity

    graph._instrument_name = resolve_instrument_identity(req.ticker).get("company_name")
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


def real_chat_llm_factory(model: str | None = None):
    """Build (chat_llm, vision_llm) LangChain models from DEFAULT_CONFIG.

    Both use the configured provider. ``model`` overrides the chat model when
    provided (still on the configured provider); otherwise falls back to the
    configured quick_think_llm. The vision model must support image input
    (anthropic / google / openai families). set_config() makes the dataflows
    vendor routing match the configured data_vendors.
    """
    from tradingagents.dataflows.config import set_config
    from tradingagents.llm_clients import create_llm_client

    config = DEFAULT_CONFIG.copy()
    set_config(config)

    provider = config["llm_provider"]
    chat_model = model or config["quick_think_llm"]
    base_url = config.get("backend_url")

    client = create_llm_client(provider=provider, model=chat_model, base_url=base_url)
    chat_llm = client.get_llm()
    vision_llm = chat_llm
    return chat_llm, vision_llm


@app.on_event("startup")
def _wire_graph_factory():
    if app.state.graph_factory is None:
        app.state.graph_factory = real_graph_factory
    if app.state.chat_llm_factory is None:
        app.state.chat_llm_factory = real_chat_llm_factory
    if app.state.scheduler is None:
        from api.scheduler import QueueScheduler

        app.state.scheduler = QueueScheduler(app)
    if app.state.startup_cache_clearer is None:
        app.state.startup_cache_clearer = StartupCacheClearer(DEFAULT_CONFIG["data_cache_dir"])

    def _advance_after_cache_clear(state: dict) -> None:
        if state.get("status") == "completed" and app.state.scheduler is not None:
            app.state.scheduler.advance()

    app.state.startup_cache_clearer.start(on_complete=_advance_after_cache_clear)
    # recover from a crash mid-run, then resume any leftover queue
    get_store().reset_orphaned_runs()
    app.state.scheduler.advance()
    if _startup_model_check_enabled():
        _run_model_health_check()
