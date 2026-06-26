"""Queue routes: enqueue a batch, inspect, remove, clear, reorder."""

import uuid

from fastapi import APIRouter, HTTPException, Request, Response

from api.schemas import AnalysisRequest, EnqueueRequest, QueueState, ReorderRequest

router = APIRouter(prefix="/api/queue", tags=["queue"])


@router.post("")
def enqueue(req: EnqueueRequest, request: Request) -> dict:
    from api.main import get_store

    store = get_store()
    shared = req.model_dump(exclude={"tickers", "ticker_names"})
    run_ids: list[str] = []
    for ticker in req.tickers:
        run_id = uuid.uuid4().hex
        analysis = AnalysisRequest(ticker=ticker, **shared)
        store.enqueue_run(
            run_id=run_id,
            ticker=ticker,
            trade_date=req.trade_date,
            asset_type=req.asset_type,
            config=analysis.model_dump(),
            instrument_name=req.ticker_names.get(ticker),
        )
        run_ids.append(run_id)

    request.app.state.scheduler.advance()
    queue = store.list_queue()
    return {
        "run_ids": run_ids,
        "running_run_id": queue.running.run_id if queue.running else None,
        "queue": queue.model_dump(),
    }


@router.get("", response_model=QueueState)
def get_queue() -> QueueState:
    from api.main import get_store

    return get_store().list_queue()


@router.delete("/{run_id}", status_code=204)
def remove_item(run_id: str) -> Response:
    from api.main import get_store

    if not get_store().remove_pending(run_id):
        raise HTTPException(status_code=409, detail="run is not pending")
    return Response(status_code=204)


@router.delete("")
def clear_queue() -> dict:
    from api.main import get_store

    return {"removed": get_store().clear_pending()}


@router.patch("/order", response_model=QueueState)
def reorder(req: ReorderRequest) -> QueueState:
    from api.main import get_store

    store = get_store()
    store.reorder_pending(req.ordered_run_ids)
    return store.list_queue()
