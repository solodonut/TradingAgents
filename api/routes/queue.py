"""Queue routes: enqueue a batch, inspect, remove, clear, reorder."""

import uuid

from fastapi import APIRouter, HTTPException, Request, Response

from api.schemas import (
    AnalysisRequest,
    EnqueueRequest,
    ParallelismState,
    QueueState,
    ReorderRequest,
)
from api.startup_cache import assert_startup_cache_ready

router = APIRouter(prefix="/api/queue", tags=["queue"])


@router.post("")
def enqueue(req: EnqueueRequest, request: Request) -> dict:
    assert_startup_cache_ready(request)
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
        "running_run_ids": [item.run_id for item in queue.running],
        "queue": queue.model_dump(),
    }


@router.get("", response_model=QueueState)
def get_queue() -> QueueState:
    from api.main import get_store

    return get_store().list_queue()


@router.get("/parallelism", response_model=ParallelismState)
def get_parallelism() -> ParallelismState:
    from api.main import get_store
    from api.scheduler import read_max_parallel

    return ParallelismState(max_parallel_runs=read_max_parallel(get_store()))


@router.put("/parallelism", response_model=ParallelismState)
def set_parallelism(req: ParallelismState, request: Request) -> ParallelismState:
    from api.main import get_store
    from api.scheduler import MAX_PARALLEL_SETTING, read_max_parallel

    store = get_store()
    store.set_setting(MAX_PARALLEL_SETTING, str(req.max_parallel_runs))
    # Raising the limit should start waiting runs right away; lowering it only
    # affects future launches (in-flight runs are never killed).
    if request.app.state.scheduler is not None:
        request.app.state.scheduler.advance()
    return ParallelismState(max_parallel_runs=read_max_parallel(store))


@router.delete("/{run_id}", status_code=204)
def remove_item(run_id: str, request: Request) -> Response:
    assert_startup_cache_ready(request)
    from api.main import get_store

    if not get_store().remove_pending(run_id):
        raise HTTPException(status_code=409, detail="run is not pending")
    return Response(status_code=204)


@router.delete("")
def clear_queue(request: Request) -> dict:
    assert_startup_cache_ready(request)
    from api.main import get_store

    return {"removed": get_store().clear_pending()}


@router.patch("/order", response_model=QueueState)
def reorder(req: ReorderRequest, request: Request) -> QueueState:
    assert_startup_cache_ready(request)
    from api.main import get_store

    store = get_store()
    store.reorder_pending(req.ordered_run_ids)
    return store.list_queue()
