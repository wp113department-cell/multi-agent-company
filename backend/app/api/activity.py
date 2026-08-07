"""Activity Stream API — SSE + control endpoints (P1).

GET  /api/tasks/{task_id}/stream   — SSE event stream
POST /api/tasks/{task_id}/stop     — set abort flag (user clicked Stop)
POST /api/tasks/{task_id}/resume   — clear abort, inject message + files
POST /api/tasks/{task_id}/cancel   — terminal, irreversible stop (AUDIT_Q_BATCH08 §14)
GET  /api/tasks/{task_id}/tokens   — cumulative token usage
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import VALID_TRANSITIONS
from app.db.repository import TransitionError, get_task, transition_task
from app.middleware.rbac import require_authenticated
from app.services.activity_stream import get_activity_registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["activity"])

# Statuses with no outgoing transitions (db/models.py::VALID_TRANSITIONS) —
# the real, structural distinction between Cancel and Stop/Resume: a stopped
# task can always be resumed, a task in one of these statuses never can.
_TERMINAL_STATUSES = frozenset(
    status for status, targets in VALID_TRANSITIONS.items() if not targets
)


class ResumePayload(BaseModel):
    message: str = ""
    files: list[dict[str, Any]] = []


@router.get("/{task_id}/stream")
async def stream_task_events(
    task_id: str, _actor: str = Depends(require_authenticated)
) -> StreamingResponse:
    """SSE event stream for a running task.

    Creates a stream on demand if one doesn't exist (agents that were started
    without a task_id still get a stream so the UI can subscribe).

    Gap-closure Stage 3 Day 63 (answers.md Appendix finding #11) — this was
    the one endpoint in this file without `require_authenticated`, unlike
    its stop/resume/tokens siblings below: when `jwt_auth_enabled=true`,
    anyone who could guess/enumerate a task_id could read that task's live
    tool-call/output stream with no authentication at all.
    """
    registry = get_activity_registry()
    stream = registry.get_or_create(task_id)

    async def _generate() -> AsyncIterator[str]:
        # Day 18 — 15s matches the plan's own heartbeat interval (and
        # OpenCode's real constant); the previous 30s meant the plan's own
        # "heartbeat tested with 16s wait" success criterion could never
        # observe one in time.
        async for event in stream.subscribe(timeout=15.0):
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
async def stop_task(
    task_id: str, _actor: str = Depends(require_authenticated)
) -> dict[str, Any]:
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
async def resume_task(
    task_id: str,
    payload: ResumePayload,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """Resume after a stop: clears abort flag and injects a user message.

    AUDIT_Q_BATCH08 §14 "Cancel (distinct terminal state)": refuses to
    resume a task whose DB status is terminal (cancelled/completed/failed —
    no outgoing VALID_TRANSITIONS) — without this check, Stop/Resume was the
    only pause primitive and it was always resumable even after a Cancel,
    which would have made Cancel indistinguishable from Stop in practice.
    Best-effort: a non-numeric task_id (fleet/Executive synthetic runs with
    no backing DevTask row) skips the DB check entirely, exactly like
    cancel_task's own best-effort DB transition below.
    """
    registry = get_activity_registry()
    stream = registry.get(task_id)
    if stream is None:
        raise HTTPException(
            status_code=404, detail=f"No active stream for task {task_id!r}"
        )

    try:
        numeric_id = int(task_id)
    except (TypeError, ValueError):
        numeric_id = None
    if numeric_id is not None:
        task = await get_task(db, numeric_id)
        if task is not None and task.status in _TERMINAL_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Task {task_id} is {task.status!r} — cannot resume a "
                    "cancelled or finished task."
                ),
            )

    stream.set_resume(payload.message, payload.files)
    logger.info("Resume requested for task %s (msg=%s)", task_id, payload.message[:80])
    return {"ok": True, "task_id": task_id, "message": "Resume signal sent."}


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """Terminal cancel — AUDIT_Q_BATCH08 §14 "Cancel (distinct terminal
    state)": previously the DB's VALID_TRANSITIONS state machine had no
    "cancelled"/"paused" status at all, and Stop/Resume (above) was the only
    pause primitive, always resumable — there was no distinct, irreversible
    cancel. This sets the same in-process abort flag Stop uses (halts the
    agent loop after its current tool call) AND transitions the task to the
    terminal "cancelled" DB status, so — unlike Stop — resume_task() above
    will refuse to resume it afterward.

    Best-effort on the DB transition, mirroring
    app/fleet/failure_ladder.py's abort()/request_human_review(): many real
    agent runs (fleet agents, the Executive) have no backing DevTask row, so
    a non-numeric task_id or a task already in a state with no "cancelled"
    transition (e.g. already completed) is not an error here — the
    in-process abort still fires either way.
    """
    registry = get_activity_registry()
    existed = registry.set_abort(task_id)
    if not existed:
        stream = registry.get_or_create(task_id)
        stream.set_abort()

    transitioned = False
    try:
        numeric_id = int(task_id)
    except (TypeError, ValueError):
        numeric_id = None
    if numeric_id is not None:
        try:
            await transition_task(db, numeric_id, "cancelled")
            transitioned = True
        except (TransitionError, ValueError):
            transitioned = False

    logger.info(
        "Cancel requested for task %s (db_transitioned=%s)", task_id, transitioned
    )
    return {
        "ok": True,
        "task_id": task_id,
        "cancelled": transitioned,
        "message": "Cancel signal sent."
        + ("" if transitioned else " (no matching task row to transition)"),
    }


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
