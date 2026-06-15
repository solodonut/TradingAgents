"""Analysis routes: start run, SSE stream, report download."""

import queue
import threading
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sse_starlette.sse import EventSourceResponse

from api.runner import AnalysisRunner
from api.schemas import AnalysisRequest

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

_REPORT_ORDER = [
    ("market_report", "市场分析"),
    ("sentiment_report", "情绪分析"),
    ("news_report", "新闻分析"),
    ("fundamentals_report", "基本面分析"),
    ("investment_plan", "研究经理决策"),
    ("trader_investment_plan", "交易计划"),
    ("final_trade_decision", "组合经理最终决策"),
]


@router.post("")
def start_analysis(req: AnalysisRequest, request: Request) -> dict:
    from api.main import get_store

    store = get_store()
    if store.has_running_run():
        raise HTTPException(status_code=409, detail="another analysis is running")

    run_id = uuid.uuid4().hex
    store.insert_run(
        run_id=run_id,
        ticker=req.ticker,
        trade_date=req.trade_date,
        asset_type=req.asset_type,
        config=req.model_dump(),
    )

    graph, init_state, decision, final_state = request.app.state.graph_factory(req)

    q: queue.Queue = queue.Queue()
    request.app.state.queues[run_id] = q
    runner = AnalysisRunner(store=store, event_queue=q)

    thread = threading.Thread(
        target=runner.run,
        kwargs={
            "run_id": run_id,
            "graph": graph,
            "init_state": init_state,
            "decision": decision,
            "final_state": final_state,
        },
        daemon=True,
    )
    thread.start()
    return {"run_id": run_id}


@router.get("/{run_id}/stream")
async def stream_analysis(run_id: str, request: Request) -> EventSourceResponse:
    q = request.app.state.queues.get(run_id)
    if q is None:
        raise HTTPException(status_code=404, detail="run not found or already drained")

    async def event_generator():
        import asyncio

        while True:
            try:
                item = await asyncio.to_thread(q.get, True, 1.0)
            except queue.Empty:
                if await request.is_disconnected():
                    break
                continue
            if item is None:
                break
            import json

            yield {"event": item["event"], "data": json.dumps(item["data"])}
        request.app.state.queues.pop(run_id, None)

    return EventSourceResponse(event_generator())


@router.get("/{run_id}/report", response_class=PlainTextResponse)
def download_report(run_id: str) -> str:
    from api.main import get_store

    run = get_store().get_run(run_id)
    if run is None or run.result is None:
        raise HTTPException(status_code=404, detail="report not available")

    parts = [f"# TradingAgents 分析报告 — {run.ticker} ({run.trade_date})\n"]
    if run.decision:
        parts.append(f"**决策: {run.decision}**\n")
    for key, title in _REPORT_ORDER:
        content = run.result.get(key)
        if content:
            parts.append(f"\n## {title}\n\n{content}\n")
    return "\n".join(parts)
