"""Fleet Enhancement Dashboard API (Day 9).

The 5 self-improvement agents (agent_performance_reviewer, agent_debugger,
agent_advisor, knowledge_curator, quality_auditor) file `enhancement_requests`
rows during their autonomous SCAN phase. Nothing acts until a human approves a
specific row here — approve kicks off that agent's APPLY phase in the
background, streamed live via the existing P1 Activity Stream
(GET /api/tasks/{trace_id}/stream). Reject is terminal.

GET  /api/fleet/requests            — list, filterable by agent/status/priority
GET  /api/fleet/requests/{id}       — detail
POST /api/fleet/requests/{id}/approve
POST /api/fleet/requests/{id}/reject
GET  /api/fleet/requests/stream     — SSE: dashboard-level events (new request,
                                       status changed) — NOT the same channel as
                                       a specific approved run's activity feed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import EnhancementRequest
from app.services.activity_stream import get_activity_registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/fleet", tags=["fleet-dashboard"])

_DASHBOARD_STREAM_KEY = "fleet-dashboard"


def _push_dashboard_event(event_type: str, payload: dict[str, Any]) -> None:
    """Broadcast a dashboard-level event (new request / status change) — distinct from
    the per-run activity stream used to watch one approved request execute."""
    stream = get_activity_registry().get_or_create(_DASHBOARD_STREAM_KEY)
    stream.push({"type": event_type, **payload})


def _serialize(row: EnhancementRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "agentName": row.agent_name,
        "title": row.title,
        "description": row.description,
        "category": row.category,
        "priority": row.priority,
        "evidence": row.evidence,
        "status": row.status,
        "filesTouched": list(row.files_touched or []),
        "commitSha": row.commit_sha,
        "restartRequired": row.restart_required,
        "error": row.error,
        "traceId": row.trace_id,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "decidedAt": row.decided_at.isoformat() if row.decided_at else None,
        "decidedBy": row.decided_by,
        "completedAt": row.completed_at.isoformat() if row.completed_at else None,
    }


@router.get("/requests")
async def list_requests(
    agent: str | None = Query(default=None),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    q = select(EnhancementRequest).order_by(EnhancementRequest.created_at.desc())
    if agent:
        q = q.where(EnhancementRequest.agent_name == agent)
    if status:
        q = q.where(EnhancementRequest.status == status)
    if priority:
        q = q.where(EnhancementRequest.priority == priority)
    result = await db.execute(q.limit(200))
    rows = result.scalars().all()
    return [_serialize(r) for r in rows]


@router.get("/requests/{request_id}")
async def get_request(
    request_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    row = await db.get(EnhancementRequest, request_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"No enhancement request #{request_id}"
        )
    return _serialize(row)


# ---------------------------------------------------------------------------
# APPLY-phase dispatch — lazy-imported so a broken/missing agent module never
# breaks the whole router at import time.
# ---------------------------------------------------------------------------


def _apply_dispatch() -> dict[str, Callable[[int, str, str], Any]]:
    from app.agents.agent_debugger import run_agent_debugger_apply
    from app.agents.agent_performance_reviewer import (
        run_agent_performance_reviewer_apply,
    )
    from app.agents.knowledge_curator import run_knowledge_curator_apply
    from app.agents.quality_auditor import run_quality_auditor_apply

    return {
        "agent_performance_reviewer": run_agent_performance_reviewer_apply,
        "agent_debugger": run_agent_debugger_apply,
        "knowledge_curator": run_knowledge_curator_apply,
        "quality_auditor": run_quality_auditor_apply,
        # agent_advisor is scan-only by design (see docs/DAY9_PLAN.md) — approving one
        # of its requests is a no-op signal that a human has acted on the advice; there
        # is no code for it to apply itself.
    }


async def _run_apply_phase(
    request_id: int, agent_name: str, description: str, trace_id: str
) -> None:
    """Background task — runs the APPLY phase and writes the result back to the row."""
    from app.db.session import get_async_session

    dispatch = _apply_dispatch()
    apply_fn = dispatch.get(agent_name)

    async def _mark(**fields: Any) -> None:
        async with get_async_session() as session:
            row = await session.get(EnhancementRequest, request_id)
            if row is None:
                return
            for k, v in fields.items():
                setattr(row, k, v)
            await session.commit()

    if apply_fn is None:
        await _mark(status="completed", completed_at=datetime.now(timezone.utc))
        _push_dashboard_event(
            "status_changed", {"id": request_id, "status": "completed"}
        )
        return

    try:
        result = await asyncio.to_thread(apply_fn, request_id, description, trace_id)
        status = "completed" if result.status == "completed" else "failed"
        await _mark(
            status=status,
            files_touched=list(result.files_touched or []),
            restart_required=True,
            completed_at=datetime.now(timezone.utc),
            error=(
                None
                if status == "completed"
                else "Apply phase did not verify successfully"
            ),
        )
        if status == "completed":
            # Gap-closure (2026-07-23): a human-approved, data-driven fleet
            # improvement was just successfully carried out — a genuine
            # "Learning Signal" (Doc 11's 4th memory category, previously
            # never written anywhere). Best-effort: a memory-write hiccup
            # must never turn an otherwise-successful apply into a reported
            # failure.
            try:
                from app.memory.store import embed_learning_signal

                async with get_async_session() as session:
                    await embed_learning_signal(
                        agent_name,
                        description,
                        result.summary,
                        session,
                    )
            except Exception:
                logger.warning(
                    "Failed to record learning signal for request #%s (%s)",
                    request_id,
                    agent_name,
                    exc_info=True,
                )
    except Exception as exc:
        logger.exception(
            "APPLY phase failed for request #%s (%s)", request_id, agent_name
        )
        await _mark(
            status="failed",
            error=str(exc)[:2000],
            completed_at=datetime.now(timezone.utc),
        )
    finally:
        _push_dashboard_event("status_changed", {"id": request_id})


class DecisionPayload(BaseModel):
    decided_by: str = "admin"


@router.post("/requests/{request_id}/approve")
async def approve_request(
    request_id: int,
    payload: DecisionPayload | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(EnhancementRequest, request_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"No enhancement request #{request_id}"
        )
    if row.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Request #{request_id} is already {row.status!r}, not pending",
        )

    trace_id = uuid.uuid4().hex[:12]
    row.status = "in_progress"
    row.decided_at = datetime.now(timezone.utc)
    row.decided_by = payload.decided_by if payload else "admin"
    row.trace_id = trace_id
    await db.commit()

    get_activity_registry().get_or_create(trace_id)
    asyncio.create_task(
        _run_apply_phase(request_id, row.agent_name, row.description, trace_id)
    )
    _push_dashboard_event("status_changed", {"id": request_id, "status": "in_progress"})

    return {"ok": True, "id": request_id, "status": "in_progress", "traceId": trace_id}


@router.post("/requests/{request_id}/reject")
async def reject_request(
    request_id: int,
    payload: DecisionPayload | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(EnhancementRequest, request_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"No enhancement request #{request_id}"
        )
    if row.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Request #{request_id} is already {row.status!r}, not pending",
        )

    row.status = "rejected"
    row.decided_at = datetime.now(timezone.utc)
    row.decided_by = payload.decided_by if payload else "admin"
    await db.commit()
    _push_dashboard_event("status_changed", {"id": request_id, "status": "rejected"})

    return {"ok": True, "id": request_id, "status": "rejected"}


@router.get("/requests/stream")
async def stream_dashboard_events() -> StreamingResponse:
    """SSE: new-request / status-change events for the in-app notification badge and
    live-updating list. Distinct from GET /api/tasks/{trace_id}/stream, which streams one
    specific approved request's execution."""
    stream = get_activity_registry().get_or_create(_DASHBOARD_STREAM_KEY)

    async def _generate() -> AsyncIterator[str]:
        async for event in stream.subscribe(timeout=30.0):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
