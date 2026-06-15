"""History routes: list, detail, delete."""

from fastapi import APIRouter, HTTPException, Response

from api.main import get_store
from api.schemas import HistorySummary, RunResult

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("", response_model=list[HistorySummary])
def list_history() -> list[HistorySummary]:
    return get_store().list_runs()


@router.get("/{run_id}", response_model=RunResult)
def get_history(run_id: str) -> RunResult:
    run = get_store().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.delete("/{run_id}", status_code=204)
def delete_history(run_id: str) -> Response:
    store = get_store()
    if store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    store.delete_run(run_id)
    return Response(status_code=204)
