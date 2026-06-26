"""History routes: list, detail, delete."""

from fastapi import APIRouter, HTTPException, Response

from api.main import get_store
from api.schemas import HistorySummary, RunResult
from tradingagents.dataflows.ticker_name import resolve_ticker_name

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("", response_model=list[HistorySummary])
def list_history() -> list[HistorySummary]:
    store = get_store()
    return [_with_instrument_name(store, item) for item in store.list_runs()]


@router.get("/{run_id}", response_model=RunResult)
def get_history(run_id: str) -> RunResult:
    store = get_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _with_instrument_name(store, run)


@router.delete("/{run_id}", status_code=204)
def delete_history(run_id: str) -> Response:
    store = get_store()
    if store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    store.delete_run(run_id)
    return Response(status_code=204)


def _with_instrument_name(store, run):
    if run.instrument_name or not _should_backfill_name(run.ticker):
        return run
    name = resolve_ticker_name(run.ticker)
    if not name:
        return run
    store.set_instrument_name(run.run_id, name)
    return run.model_copy(update={"instrument_name": name})


def _should_backfill_name(ticker: str) -> bool:
    bare = ticker.strip().upper().split(".", 1)[0]
    return len(bare) == 6 and bare.isdigit()
