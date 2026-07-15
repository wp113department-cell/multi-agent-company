"""Epics API — POST /api/epics, GET /api/epics/:id, POST /api/epics/:id/approve|reject."""
from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import DevTask, Epic, PolicyApproval
from app.event_bus.bus import publish_event
from app.event_bus.models import GridironEvent
from app.middleware.rbac import require_approver
from app.pipeline.cost_controller import estimate_epic_cost

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/epics", tags=["epics"])


# ---- Request / Response schemas ----

class CreateEpicRequest(BaseModel):
    title: str
    description: str
    complexity_multiplier: float = 1.0


class ApprovePolicyRequest(BaseModel):
    policy_id: int
    file_path: str | None = None
    decision: str = "approved"


class EpicResponse(BaseModel):
    epic_id: str
    title: str
    description: str
    status: str
    cost_estimate: float | None
    cost_actual: float | None
    halt_reason: str | None
    created_at: str
    updated_at: str
    tasks: list[dict[str, Any]]


# ---- Helper ----

def _epic_to_response(epic: Epic, tasks: list[DevTask]) -> dict[str, Any]:
    return {
        "epicId": epic.epic_id,
        "title": epic.title,
        "description": epic.description,
        "status": epic.status,
        "costEstimate": float(epic.cost_estimate) if epic.cost_estimate else None,
        "costActual": float(epic.cost_actual) if epic.cost_actual else None,
        "haltReason": epic.halt_reason,
        "createdAt": epic.created_at.isoformat(),
        "updatedAt": epic.updated_at.isoformat(),
        "tasks": [
            {
                "taskId": t.id,
                "title": t.title,
                "status": t.status,
                "createdAt": t.created_at.isoformat(),
            }
            for t in tasks
        ],
    }


# ---- Routes ----

@router.post("")
async def create_epic(
    body: CreateEpicRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new epic and start the epic manager pipeline in the background."""
    epic_id = str(uuid.uuid4())

    # Cost pre-estimate (5 subtasks assumed before planning runs)
    estimate = await estimate_epic_cost(
        subtask_count=5,
        db=db,
        complexity_multiplier=body.complexity_multiplier,
    )

    epic = Epic(
        epic_id=epic_id,
        title=body.title,
        description=body.description,
        status="pending",
        cost_estimate=Decimal(str(estimate.estimated_cost_usd)),
    )
    db.add(epic)
    await db.commit()
    await db.refresh(epic)

    # Fire-and-forget: start the epic manager pipeline
    asyncio.create_task(_launch_epic_manager(epic_id, body.description))

    return {
        "epicId": epic_id,
        "status": epic.status,
        "costEstimate": float(estimate.estimated_cost_usd),
        "requiresCostApproval": estimate.requires_approval,
        "message": "Epic created. Manager pipeline starting.",
    }


@router.get("")
async def list_epics(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    """List all epics, newest first."""
    result = await db.execute(select(Epic).order_by(Epic.created_at.desc()))
    epics = list(result.scalars().all())
    return [
        {
            "epicId": e.epic_id,
            "title": e.title,
            "status": e.status,
            "costEstimate": float(e.cost_estimate) if e.cost_estimate else None,
            "costActual": float(e.cost_actual) if e.cost_actual else None,
            "haltReason": e.halt_reason,
            "createdAt": e.created_at.isoformat(),
        }
        for e in epics
    ]


@router.get("/{epic_id}")
async def get_epic(epic_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Get an epic with all child tasks."""
    result = await db.execute(select(Epic).where(Epic.epic_id == epic_id))
    epic = result.scalar_one_or_none()
    if not epic:
        raise HTTPException(status_code=404, detail=f"Epic {epic_id} not found")

    task_result = await db.execute(select(DevTask).where(DevTask.epic_id == epic_id))
    tasks = list(task_result.scalars().all())

    return _epic_to_response(epic, tasks)


@router.post("/{epic_id}/approve")
async def approve_epic(
    epic_id: str,
    user_id: str = Depends(require_approver),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Approve the epic batched approval package (approver role required)."""
    result = await db.execute(select(Epic).where(Epic.epic_id == epic_id))
    epic = result.scalar_one_or_none()
    if not epic:
        raise HTTPException(status_code=404, detail=f"Epic {epic_id} not found")

    if epic.status not in ("ready_for_review", "pending_cost_approval"):
        raise HTTPException(
            status_code=409,
            detail=f"Epic is in status {epic.status!r}; must be ready_for_review or pending_cost_approval to approve",
        )

    epic.status = "approved"
    await db.commit()

    await publish_event(GridironEvent(
        event_type="epic.approved",
        epic_id=epic_id,
        payload={"approved_by": user_id},
        emitted_by="api",
    ))

    return {"epicId": epic_id, "status": "approved", "approvedBy": user_id}


@router.post("/{epic_id}/reject")
async def reject_epic(
    epic_id: str,
    user_id: str = Depends(require_approver),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reject the epic (approver role required)."""
    result = await db.execute(select(Epic).where(Epic.epic_id == epic_id))
    epic = result.scalar_one_or_none()
    if not epic:
        raise HTTPException(status_code=404, detail=f"Epic {epic_id} not found")

    if epic.status not in ("ready_for_review", "pending_cost_approval", "halted"):
        raise HTTPException(
            status_code=409,
            detail=f"Epic is in status {epic.status!r}; cannot reject",
        )

    epic.status = "rejected"
    await db.commit()

    await publish_event(GridironEvent(
        event_type="epic.rejected",
        epic_id=epic_id,
        payload={"rejected_by": user_id},
        emitted_by="api",
    ))

    return {"epicId": epic_id, "status": "rejected", "rejectedBy": user_id}


@router.post("/{epic_id}/approve-cost")
async def approve_epic_cost(
    epic_id: str,
    user_id: str = Depends(require_approver),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Approve cost for an epic blocked on cost approval (approver role required)."""
    result = await db.execute(select(Epic).where(Epic.epic_id == epic_id))
    epic = result.scalar_one_or_none()
    if not epic:
        raise HTTPException(status_code=404, detail=f"Epic {epic_id} not found")

    if epic.status != "pending_cost_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Epic is in status {epic.status!r}; must be pending_cost_approval",
        )

    epic.status = "pending"
    await db.commit()

    # Re-launch the manager with cost approval granted
    asyncio.create_task(_launch_epic_manager(epic_id, epic.description))

    return {"epicId": epic_id, "status": "pending", "message": "Cost approved. Manager pipeline restarting."}


@router.post("/{epic_id}/policy-approval")
async def record_policy_approval(
    epic_id: str,
    body: ApprovePolicyRequest,
    user_id: str = Depends(require_approver),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Record a policy approval (or rejection) for a blocking gate on this epic."""
    from app.policy.engine_v2 import record_approval

    approval = await record_approval(
        policy_id=body.policy_id,
        approver_role="human",
        decision=body.decision,
        db=db,
        epic_id=epic_id,
        file_path=body.file_path,
    )
    await db.commit()

    return {
        "approvalId": approval.id,
        "policyId": body.policy_id,
        "epicId": epic_id,
        "decision": body.decision,
        "approvedBy": user_id,
    }


@router.get("/batch-review", summary="List epics and tasks awaiting review in bulk")
async def batch_review(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Return all epics + tasks that are ready for human review, grouped for batch approval.

    Returns epics in 'ready_for_review', 'pending_cost_approval', and tasks in
    'ready_for_review' or 'awaiting_approval' — ordered by age (oldest first).
    """
    from sqlalchemy import or_

    epic_result = await db.execute(
        select(Epic)
        .where(Epic.status.in_(["ready_for_review", "pending_cost_approval"]))
        .order_by(Epic.created_at.asc())
    )
    epics = list(epic_result.scalars().all())

    task_result = await db.execute(
        select(DevTask)
        .where(DevTask.status.in_(["ready_for_review", "awaiting_approval"]))
        .order_by(DevTask.created_at.asc())
    )
    tasks = list(task_result.scalars().all())

    return {
        "epics": [
            {
                "epicId": e.epic_id,
                "title": e.title,
                "status": e.status,
                "costEstimate": float(e.cost_estimate) if e.cost_estimate else None,
                "haltReason": e.halt_reason,
                "age": (
                    __import__("datetime").datetime.utcnow() - e.created_at
                ).total_seconds() / 3600,
                "createdAt": e.created_at.isoformat(),
            }
            for e in epics
        ],
        "tasks": [
            {
                "taskId": t.id,
                "title": t.title,
                "description": t.description[:300] if t.description else "",
                "status": t.status,
                "epicId": t.epic_id,
                "age": (
                    __import__("datetime").datetime.utcnow() - t.created_at
                ).total_seconds() / 3600,
                "createdAt": t.created_at.isoformat(),
            }
            for t in tasks
        ],
        "totalPendingReview": len(epics) + len(tasks),
    }


# ---- Background task ----

async def _launch_epic_manager(epic_id: str, goal: str) -> None:
    """Fire-and-forget: run the epic manager pipeline."""
    from app.db.session import get_async_session
    from app.agents.manager import run_epic_manager

    try:
        async with get_async_session() as db:
            await run_epic_manager(epic_id=epic_id, goal=goal, db=db)
    except Exception:
        logger.exception("Epic manager pipeline failed for epic %s", epic_id)
