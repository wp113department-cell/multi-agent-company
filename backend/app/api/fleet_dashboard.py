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
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import AgentRun, EnhancementRequest, MemoryEmbedding
from app.middleware.rbac import require_approver
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
# Checkpoint / Rollback — AUDIT_Q_BATCH08 §14 "Rollback (NO — confirmed not
# auto-wired)". app.fleet.fleet_checkpoint.rollback_to (re-exported as
# app.fleet.failure_ladder.rollback) was a real function with zero
# production callers — deliberately manual-only per that module's own
# docstring, matching the precedent already set for prompt_registry.deploy()
# before it got a real caller (app/agents/tools.py's
# _propose_and_deploy_role_prompt). These two endpoints are that caller: a
# human-operated "inspect checkpoints, roll one back" dashboard action, not
# an automatic trigger — the same judgment-call boundary this module's own
# comment draws around Rollback/Resume being intentionally different from
# Checkpoint/Escalate/Abort/Human Review/Retry (which do have automatic
# call sites).
# ---------------------------------------------------------------------------


@router.get("/checkpoints")
async def list_checkpoints(
    agent_name: str | None = Query(default=None),
    task_id: str | None = Query(default=None),
    _approver: str = Depends(require_approver),
) -> list[dict[str, Any]]:
    """List saved agent-run checkpoints (app.fleet.fleet_checkpoint's
    in-process ring buffer), optionally filtered — the real prerequisite for
    an operator to pick a checkpoint_id to roll back to below."""
    from app.fleet.fleet_checkpoint import get_checkpoint_store

    store = get_checkpoint_store()
    checkpoints = store.list_checkpoints(agent_name=agent_name, task_id=task_id)
    return [c.to_dict() for c in checkpoints]


@router.post("/checkpoints/{checkpoint_id}/rollback")
async def rollback_checkpoint(
    checkpoint_id: str,
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Operator-invoked rollback to a previously saved checkpoint. Returns
    the restored state snapshot for inspection and records a health event so
    the action has an audit trail (mirrors
    app/fleet/failure_ladder.py::escalate()'s own event-publishing shape).

    Does not re-inject the restored state into a live, still-running agent
    process — that path belongs to LangGraph's own checkpointer (a resumed
    graph.stream() call against the same thread_id), which this in-process
    ring-buffer checkpoint store is deliberately separate from (see
    fleet_checkpoint.py's own module docstring: it exists for a
    "save -> restore -> rollback" cycle an agent's own code can call
    inline before/after a risky operation). This endpoint's job is making
    the rollback primitive itself reachable by a human, closing the "zero
    production callers" finding — not building a second, riskier live-run
    state-mutation path in the same change.
    """
    from app.fleet.failure_ladder import rollback
    from app.fleet.fleet_checkpoint import get_checkpoint_store
    from app.fleet.fleet_events import health_updated, publish

    store = get_checkpoint_store()
    meta = store.get(checkpoint_id)
    if meta is None:
        raise HTTPException(
            status_code=404, detail=f"Checkpoint {checkpoint_id!r} not found"
        )

    try:
        restored_state = rollback(checkpoint_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    logger.warning(
        "Operator-invoked rollback: checkpoint %s (agent=%s, task=%s, label=%r)",
        checkpoint_id,
        meta.agent_name,
        meta.task_id,
        meta.label,
    )
    try:
        publish(
            health_updated(
                meta.agent_name or "unknown",
                health="degraded",
                state=(
                    f"operator rolled back to checkpoint {checkpoint_id} "
                    f"({meta.label or 'unlabeled'})"
                ),
            )
        )
    except Exception:
        pass

    return {
        "checkpointId": checkpoint_id,
        "agentName": meta.agent_name,
        "taskId": meta.task_id,
        "label": meta.label,
        "createdAt": meta.created_at.isoformat(),
        "restoredState": restored_state,
    }


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
    _approver: str = Depends(require_approver),
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
    _approver: str = Depends(require_approver),
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


# ---------------------------------------------------------------------------
# Read-only reporting (MASTER_AGENT_v2.md Phase 6.2) — cost, fleet health,
# and recorded repair patterns, all over data other agents already write
# (agent_runs / memory_embeddings). No new collection, no new tables.
# ---------------------------------------------------------------------------


@router.get("/reports/cost")
async def cost_report(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Cost per agent/day, plus a per-model-tier rollup. Tier is resolved via
    ModelRouter (agent_models.json is the one live source of truth for tier —
    agent_runs.model_id is a raw model string, not stored redundantly here)."""
    from app.fleet.model_router import get_model_router

    since = datetime.now(timezone.utc) - timedelta(days=days)
    day_col = func.date_trunc("day", AgentRun.started_at)
    q = (
        select(
            AgentRun.agent_type,
            day_col.label("day"),
            func.coalesce(func.sum(AgentRun.tokens_in), 0),
            func.coalesce(func.sum(AgentRun.tokens_out), 0),
            func.coalesce(func.sum(AgentRun.cost_estimate), 0),
            func.count(AgentRun.id),
        )
        .where(AgentRun.started_at >= since)
        .group_by(AgentRun.agent_type, day_col)
        .order_by(day_col.desc())
    )
    result = await db.execute(q)
    router_ = get_model_router()

    by_agent_day: list[dict[str, Any]] = []
    tier_totals: dict[str, float] = {}
    for agent_type, day, tokens_in, tokens_out, cost_usd, run_count in result.all():
        tier = router_.route(agent_type).tier
        cost = float(cost_usd or 0)
        tier_totals[tier] = tier_totals.get(tier, 0.0) + cost
        by_agent_day.append(
            {
                "agentName": agent_type,
                "day": day.isoformat() if day else None,
                "tier": tier,
                "tokensIn": int(tokens_in or 0),
                "tokensOut": int(tokens_out or 0),
                "costUsd": cost,
                "runCount": int(run_count),
            }
        )

    return {
        "sinceDays": days,
        "byAgentDay": by_agent_day,
        "byTier": [
            {"tier": tier, "costUsd": cost}
            for tier, cost in sorted(tier_totals.items(), key=lambda kv: -kv[1])
        ],
    }


@router.get("/reports/health")
async def health_report(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    """Failure rate, active-run count, and average heartbeat staleness (for
    currently-running runs) per agent — all real agent_runs aggregates, no
    synthetic/estimated fields.

    Staleness is computed entirely server-side (`func.now() -
    last_heartbeat_at`, both real timestamptz values Postgres compares in
    its own consistent internal representation) rather than reading
    last_heartbeat_at back into Python and subtracting against a
    Python-side `datetime.now(timezone.utc)` — the two conversion paths
    (asyncpg's naive-input write path vs. its tz-aware read path) don't
    agree on the session's UTC offset, which silently skewed every
    staleness value by that offset when tried that way (caught by this
    endpoint's own real-DB test asserting an exact expected staleness)."""
    from sqlalchemy import case

    staleness_seconds = func.extract("epoch", func.now() - AgentRun.last_heartbeat_at)
    q = (
        select(
            AgentRun.agent_type,
            func.count(AgentRun.id),
            func.coalesce(func.sum(case((AgentRun.status == "failed", 1), else_=0)), 0),
            func.coalesce(
                func.sum(case((AgentRun.status == "running", 1), else_=0)), 0
            ),
            func.avg(case((AgentRun.status == "running", staleness_seconds))),
        )
        .group_by(AgentRun.agent_type)
        .order_by(AgentRun.agent_type)
    )
    result = await db.execute(q)

    report = []
    for agent_type, total, failed, active, avg_staleness in result.all():
        total = int(total)
        failed = int(failed or 0)
        report.append(
            {
                "agentName": agent_type,
                "totalRuns": total,
                "failedRuns": failed,
                "failureRate": round(failed / total, 4) if total else 0.0,
                "activeRuns": int(active or 0),
                "avgHeartbeatStalenessSeconds": (
                    round(float(avg_staleness), 1)
                    if avg_staleness is not None
                    else None
                ),
            }
        )
    report.sort(key=lambda r: -r["failureRate"])
    return report


@router.get("/reports/repair-patterns")
async def repair_patterns_report(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Most commonly recorded repair patterns — Phase 1.5's procedural
    memory (`embed_failure()` writes MemoryEmbedding rows with
    category='failure'; `summary` holds the diagnosed root cause / repair).
    Grouped by exact summary text — real occurrence counts, not a synthetic
    clustering pass."""
    q = (
        select(
            MemoryEmbedding.summary,
            func.count(MemoryEmbedding.id),
            func.max(MemoryEmbedding.created_at),
        )
        .where(MemoryEmbedding.category == "failure")
        .where(MemoryEmbedding.archived.is_(False))
        .group_by(MemoryEmbedding.summary)
        .order_by(func.count(MemoryEmbedding.id).desc())
        .limit(limit)
    )
    result = await db.execute(q)
    return [
        {
            "repairPattern": summary,
            "occurrences": int(occurrences),
            "lastSeen": last_seen.isoformat() if last_seen else None,
        }
        for summary, occurrences, last_seen in result.all()
    ]


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
