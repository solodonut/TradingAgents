"""Manual full data-cache clearing routes."""

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from api.startup_cache import StartupCacheClearer, sse_json
from tradingagents.default_config import DEFAULT_CONFIG

router = APIRouter(prefix="/api/cache", tags=["cache"])


def _get_clearer(request: Request) -> StartupCacheClearer:
    clearer = getattr(request.app.state, "manual_cache_clearer", None)
    if clearer is None:
        clearer = StartupCacheClearer(
            DEFAULT_CONFIG["data_cache_dir"], include_checkpoints=True
        )
        request.app.state.manual_cache_clearer = clearer
    return clearer


@router.post("/clear")
def clear_cache(request: Request) -> dict:
    if request.app.state.run_lock.locked():
        raise HTTPException(status_code=409, detail="分析运行中，无法清除缓存")

    clearer = _get_clearer(request)
    if clearer.is_active():
        raise HTTPException(status_code=409, detail="缓存清理正在进行")

    clearer.start()
    return clearer.snapshot()


@router.get("/status")
def cache_status(request: Request) -> dict:
    return _get_clearer(request).snapshot()


@router.get("/stream")
def stream_cache(request: Request) -> EventSourceResponse:
    def event_generator():
        for item in _get_clearer(request).subscribe():
            yield sse_json(item)

    return EventSourceResponse(event_generator())
