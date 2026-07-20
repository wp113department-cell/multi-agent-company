"""Activity Stream API — SSE + control endpoints (P1).

GET  /api/tasks/{task_id}/stream   — SSE event stream
POST /api/tasks/{task_id}/stop     — set abort flag (user clicked Stop)
POST /api/tasks/{task_id}/resume   — clear abort, inject message + files
GET  /api/tasks/{task_id}/tokens   — cumulative token usage
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.activity_stream import get_activity_registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["activity"])


class ResumePayload(BaseModel):
    message: str = ""
    files: list[dict[str, Any]] = []


@router.get("/{task_id}/stream")
async def stream_task_events(task_id: str) -> StreamingResponse:
    """SSE event stream for a running task.

    Creates a stream on demand if one doesn't exist (agents that were started
    without a task_id still get a stream so the UI can subscribe).
    """
    registry = get_activity_registry()
    stream = registry.get_or_create(task_id)

    async def _generate() -> AsyncIterator[str]:
        async for event in stream.subscribe(timeout=30.0):
            payload = json.dumps(event, default=str)
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/{task_id}/stop")
async def stop_task(task_id: str) -> dict[str, Any]:
    """Signal the agent to stop after the current tool call completes."""
    registry = get_activity_registry()
    existed = registry.set_abort(task_id)
    if not existed:
        # Create stream and set abort so next call_llm sees it
        stream = registry.get_or_create(task_id)
        stream.set_abort()
    logger.info("Stop requested for task %s", task_id)
    return {"ok": True, "task_id": task_id, "message": "Stop signal sent."}


@router.post("/{task_id}/resume")
async def resume_task(task_id: str, payload: ResumePayload) -> dict[str, Any]:
    """Resume after a stop: clears abort flag and injects a user message."""
    registry = get_activity_registry()
    stream = registry.get(task_id)
    if stream is None:
        raise HTTPException(status_code=404, detail=f"No active stream for task {task_id!r}")
    stream.set_resume(payload.message, payload.files)
    logger.info("Resume requested for task %s (msg=%s)", task_id, payload.message[:80])
    return {"ok": True, "task_id": task_id, "message": "Resume signal sent."}


@router.get("/{task_id}/tokens")
async def get_token_usage(task_id: str) -> dict[str, Any]:
    """Return current cumulative token counters for a task."""
    registry = get_activity_registry()
    stream = registry.get(task_id)
    if stream is None:
        return {"task_id": task_id, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
    tokens_in = stream.tokens_in
    tokens_out = stream.tokens_out
    cost = tokens_in * 0.000003 + tokens_out * 0.000015
    return {
        "task_id": task_id,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost, 6),
    }
