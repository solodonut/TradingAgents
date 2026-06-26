"""History routes: list, detail, delete."""

import io
import zipfile
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from api.main import get_store
from api.reporting import build_markdown_report, report_filename
from api.schemas import HistorySummary, RunResult
from tradingagents.dataflows.ticker_name import resolve_ticker_name

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("", response_model=list[HistorySummary])
def list_history() -> list[HistorySummary]:
    store = get_store()
    return [_with_instrument_name(store, item) for item in store.list_runs()]


@router.get("/reports.zip")
def download_history_reports_zip(
    run_ids: Annotated[list[str] | None, Query()] = None,
) -> StreamingResponse:
    store = get_store()
    selected = set(run_ids or [])
    runs = [
        _with_instrument_name(store, run)
        for run in store.list_runs()
        if run.status != "pending" and (not selected or run.run_id in selected)
    ]
    runs_with_reports = [run for run in runs if store.get_run(run.run_id).result]
    if not runs_with_reports:
        raise HTTPException(status_code=404, detail="no reports available")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for summary in runs_with_reports:
            run = store.get_run(summary.run_id)
            if run is None or run.result is None:
                continue
            run = _with_instrument_name(store, run)
            archive.writestr(report_filename(run), build_markdown_report(run))
    buffer.seek(0)
    filename = f"tradingagents_reports_{date.today().isoformat()}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
