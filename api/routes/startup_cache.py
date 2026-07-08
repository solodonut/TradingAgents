"""Startup cache clear status routes."""

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from api.startup_cache import get_startup_cache_clearer, sse_json

router = APIRouter(prefix="/api/startup-cache", tags=["startup-cache"])


@router.get("/status")
def startup_cache_status(request: Request) -> dict:
    clearer = get_startup_cache_clearer(request)
    if clearer is None:
        raise HTTPException(status_code=503, detail="startup cache clearer not initialized")
    return clearer.snapshot()


@router.get("/stream")
def stream_startup_cache(request: Request) -> EventSourceResponse:
    clearer = get_startup_cache_clearer(request)
    if clearer is None:
        raise HTTPException(status_code=503, detail="startup cache clearer not initialized")

    def event_generator():
        for item in clearer.subscribe():
            yield sse_json(item)

    return EventSourceResponse(event_generator())
