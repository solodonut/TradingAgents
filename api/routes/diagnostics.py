"""ETF data-endpoint diagnostics: probe every VENDOR_METHODS cell over SSE.

Read-only and NOT gated by the single-run lock — it can run during an analysis.
"""

import json
import time
from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

from tradingagents.dataflows.diagnostics import build_meta, count_probes, iter_probes

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("/etf/meta")
def etf_diagnostics_meta() -> dict:
    """供应商名单 + 每个方法的分区与说明。纯读、无网络,不走 app.state 注入。"""
    return build_meta()


@router.get("/etf/{code}")
def stream_etf_diagnostics(
    code: str,
    request: Request,
    ref_date: str | None = Query(None),
    vendors: str | None = Query(None),
) -> EventSourceResponse:
    rd = ref_date or date.today().isoformat()
    # 逗号分隔;空 / 缺省 = 全跑(None)。未知供应商名由 iter/count 静默忽略。
    vendor_set = {v.strip() for v in vendors.split(",") if v.strip()} if vendors else None
    # tests inject fakes via app.state; production uses the real matrix.
    probe_iter = getattr(request.app.state, "diagnostics_probe_iter", None) or iter_probes
    count_fn = getattr(request.app.state, "diagnostics_count", None) or count_probes

    def event_generator():
        counts = {"ok": 0, "no_data": 0, "no_perm": 0, "unavailable": 0}
        t0 = time.time()
        yield {
            "event": "start",
            "data": json.dumps({"total": count_fn(vendor_set), "code": code, "ref_date": rd}),
        }
        for cell in probe_iter(code, rd, vendor_set):
            counts[cell.status] = counts.get(cell.status, 0) + 1
            yield {"event": "cell", "data": json.dumps(asdict(cell))}
        counts["elapsed_ms"] = (time.time() - t0) * 1000
        yield {"event": "done", "data": json.dumps(counts)}

    return EventSourceResponse(event_generator())
