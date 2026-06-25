"""Service health routes."""

import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from api.service_health import generate_service_health_events

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/services/stream")
def stream_service_health() -> EventSourceResponse:
    def event_generator():
        for item in generate_service_health_events():
            yield {"event": item["event"], "data": json.dumps(item["data"])}

    return EventSourceResponse(event_generator())
