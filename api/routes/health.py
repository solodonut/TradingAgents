"""Service health routes."""

import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from api.service_health import generate_service_health_events, probe_single_service_health

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/services/stream")
def stream_service_health() -> EventSourceResponse:
    def event_generator():
        for item in generate_service_health_events():
            yield {"event": item["event"], "data": json.dumps(item["data"])}

    return EventSourceResponse(event_generator())


@router.get("/services/{service_id:path}")
def get_service_health(service_id: str) -> dict:
    status = probe_single_service_health(service_id)
    if status is None:
        raise HTTPException(status_code=404, detail="service not found")
    return status
