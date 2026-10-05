"""Epics API — POST /api/epics, GET /api/epics/:id, POST /api/epics/:id/approve|reject."""

from __future__ import annotations

from datetime import datetime, timezone

import asyncio
import logging
import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import Path as PathParam

from app.api.budget_gate import require_daily_budget
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_db
from app.db.models import DevTask, Epic, PipelineState
from app.db.repository import resolve_epic_repo_path
from app.event_bus.bus import publish_event
from app.event_bus.models import GridironEvent
from app.middleware.rbac import require_approver, require_authenticated
from app.pipeline.cost_controller import estimate_epic_cost
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

# Production audit 12: a non-UUID epic id reached asyncpg and came back as a
# 500 ("invalid UUID"); validate it at the boundary so callers get a 422.
EpicId = Annotated[
    str,
    PathParam(
        pattern=r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$"
    ),
]

router = APIRouter(prefix="/api/epics", tags=["epics"])


# ---- Request / Response schemas ----


class CreateEpicRequest(BaseModel):
    title: str
    description: str
    complexity_multiplier: float = 1.0
    # Stage 4 Cluster R Phase 1 (2026-08-05, migration 031,
    # CLUSTER_R_DESIGN.md) — mirrors CreateTaskRequest.repo_id's exact
    # optional shape. Phase 1 only persists this; execution-path wiring
    # (epic-manager graph, DevTask.repo_id inheritance) is Phase 2.
    repo_id: int | None = None


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
        "repoId": epic.repo_id,
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
@limiter.limit(get_settings().rate_limit_tasks)
async def create_epic(
    request: Request,
    body: CreateEpicRequest,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_approver),
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
        repo_id=body.repo_id,
        created_by=_actor,
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
async def list_epics(
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> list[dict[str, Any]]:
    """List epics, newest first (Qoder cross-check PROD-09-104: was unbounded —
    every epic ever created on every 5 s poll of the epics page)."""
    result = await db.execute(
        select(Epic).order_by(Epic.created_at.desc()).limit(limit)
    )
    epics = list(result.scalars().all())
    return [
        {
            "epicId": e.epic_id,
            "title": e.title,
            "status": e.status,
            "repoId": e.repo_id,
            "costEstimate": float(e.cost_estimate) if e.cost_estimate else None,
            "costActual": float(e.cost_actual) if e.cost_actual else None,
            "haltReason": e.halt_reason,
            "createdAt": e.created_at.isoformat(),
        }
        for e in epics
    ]


# Production audit 12: must stay above get_epic() — its path parameter
# matched "/batch-review" (500: invalid UUID) first, so this endpoint was unreachable.
@router.get("/batch-review", summary="List epics and tasks awaiting review in bulk")
async def batch_review(
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """Return all epics + tasks that are ready for human review, grouped for batch approval.

    Returns epics in 'ready_for_review' / 'pending_cost_approval', and tasks
    whose plan awaits approval (pipeline stage 'awaiting_approval') — the
    action this page's Approve/Reject buttons perform
    (POST /api/tasks/{id}/pipeline/approve|reject) — oldest first.

    Qoder cross-check ORCH-04-109 (2026-10-02): tasks were filtered on
    DevTask.status in ('ready_for_review', 'awaiting_approval'), but
    'awaiting_approval' is a pipeline stage, never a task status (a task
    awaiting plan approval is status 'planning'). Plans waiting for approval
    never appeared, and the listed ready_for_review tasks got buttons the
    pipeline/approve endpoint refuses (409).
    """

    epic_result = await db.execute(
        select(Epic)
        .where(
            Epic.status.in_(
                [
                    "ready_for_review",
                    "pending_cost_approval",
                    "pending_plan_approval",
                    "pending_policy_approval",
                ]
            )
        )
        .order_by(Epic.created_at.asc())
    )
    epics = list(epic_result.scalars().all())

    task_result = await db.execute(
        select(DevTask)
        .join(PipelineState, PipelineState.task_id == DevTask.id)
        .where(PipelineState.stage == "awaiting_approval")
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
                "age": (datetime.now(timezone.utc) - e.created_at).total_seconds()
                / 3600,
                "createdAt": e.created_at.isoformat(),
            }
            for e in epics
        ],
        "tasks": [
            {
                "taskId": t.id,
                "title": t.title,
                "description": t.description[:300] if t.description else "",
                "status": "awaiting_approval",
                "epicId": t.epic_id,
                "age": (datetime.now(timezone.utc) - t.created_at).total_seconds()
                / 3600,
                "createdAt": t.created_at.isoformat(),
            }
            for t in tasks
        ],
        "totalPendingReview": len(epics) + len(tasks),
    }


@router.get("/{epic_id}")
async def get_epic(
    epic_id: EpicId,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """Get an epic with all child tasks."""
    result = await db.execute(select(Epic).where(Epic.epic_id == epic_id))
    epic = result.scalar_one_or_none()
    if not epic:
        raise HTTPException(status_code=404, detail=f"Epic {epic_id} not found")

    task_result = await db.execute(select(DevTask).where(DevTask.epic_id == epic_id))
    tasks = list(task_result.scalars().all())

    return _epic_to_response(epic, tasks)


@router.post("/{epic_id}/approve", dependencies=[Depends(require_daily_budget)])
async def approve_epic(
    epic_id: EpicId,
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

    push_requested = False
    if epic.status == "ready_for_review":
        # Epic lifecycle (Qoder ORCH-04-104): approving the finished epic now
        # hands its child task to the same push / PR flow normal tasks use
        # (a git_push approval in the inbox -> push_and_create_pr on approve).
        push_requested = await _request_epic_push(epic_id, db)

    epic.status = "approved"
    await db.commit()

    await publish_event(
        GridironEvent(
            event_type="epic.approved",
            epic_id=epic_id,
            payload={"approved_by": user_id},
            emitted_by="api",
        ),
        db=db,
    )

    return {
        "epicId": epic_id,
        "status": "approved",
        "approvedBy": user_id,
        "pushApprovalRequested": push_requested,
    }


@router.post("/{epic_id}/reject")
async def reject_epic(
    epic_id: EpicId,
    user_id: str = Depends(require_approver),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reject the epic (approver role required)."""
    result = await db.execute(select(Epic).where(Epic.epic_id == epic_id))
    epic = result.scalar_one_or_none()
    if not epic:
        raise HTTPException(status_code=404, detail=f"Epic {epic_id} not found")

    if epic.status not in (
        "ready_for_review",
        "pending_cost_approval",
        "halted",
        "pending_plan_approval",
        "pending_policy_approval",
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Epic is in status {epic.status!r}; cannot reject",
        )

    epic.status = "rejected"
    await db.commit()
    await _close_epic_child(epic_id, db)

    await publish_event(
        GridironEvent(
            event_type="epic.rejected",
            epic_id=epic_id,
            payload={"rejected_by": user_id},
            emitted_by="api",
        ),
        db=db,
    )

    return {"epicId": epic_id, "status": "rejected", "rejectedBy": user_id}


@router.post("/{epic_id}/approve-cost", dependencies=[Depends(require_daily_budget)])
async def approve_epic_cost(
    epic_id: EpicId,
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

    # Qoder cross-check H-5: record the approval (and the amount approved).
    # Before, "cost approval granted" existed only in the comment: the
    # relaunched manager re-estimated, saw the same over-threshold cost and
    # halted at pending_cost_approval again — the epic could never start.
    epic.cost_approved_usd = epic.cost_estimate
    epic.cost_approved_by = user_id
    epic.halt_reason = None
    epic.status = "pending"
    await db.commit()

    asyncio.create_task(_launch_epic_manager(epic_id, epic.description))

    return {
        "epicId": epic_id,
        "status": "pending",
        "message": "Cost approved. Manager pipeline restarting.",
    }


async def _epic_child(epic_id: str, db: AsyncSession) -> DevTask | None:
    result = await db.execute(
        select(DevTask)
        .where(DevTask.epic_id == epic_id, DevTask.status != "cancelled")
        .order_by(DevTask.id.desc())
    )
    return result.scalars().first()


async def _close_epic_child(epic_id: str, db: AsyncSession) -> None:
    """Rejected epic: reject its child task, release its file reservations
    and drop its worktree (Qoder ORCH-04-104: nothing did)."""
    from app.db.repository import TransitionError, transition_task
    from app.pipeline.file_locks import release_epic_files
    from app.repo_tools.worktree import remove_worktree

    task = await _epic_child(epic_id, db)
    try:
        await release_epic_files(epic_id, db)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.warning("Could not release files of epic %s", epic_id, exc_info=True)
    if task is None:
        return
    try:
        await transition_task(db, task.id, "rejected")
        await db.commit()
    except TransitionError:
        await db.rollback()
    try:
        repo_path = resolve_epic_repo_path(
            (
                await db.execute(
                    select(Epic)
                    .options(selectinload(Epic.repo))
                    .where(Epic.epic_id == epic_id)
                )
            ).scalar_one()
        )
        await asyncio.to_thread(remove_worktree, task.id, repo_path)
    except Exception:
        logger.warning("Could not remove worktree of epic %s", epic_id, exc_info=True)


async def _request_epic_push(epic_id: str, db: AsyncSession) -> bool:
    """Create the git-push approval for the epic's child task (same helper the
    task path uses). Returns whether one was created."""
    from app.api.agents import _record_git_push_approval
    from app.repo_tools.worktree import get_diff

    task = await _epic_child(epic_id, db)
    if task is None:
        return False
    epic = (
        await db.execute(
            select(Epic).options(selectinload(Epic.repo)).where(Epic.epic_id == epic_id)
        )
    ).scalar_one()
    repo_path = resolve_epic_repo_path(epic) or get_settings().target_repo_path
    ps = (
        await db.execute(select(PipelineState).where(PipelineState.task_id == task.id))
    ).scalar_one_or_none()
    subtasks = list((ps.subtasks_json if ps else None) or [])
    files = sorted(
        {
            str(f.get("path"))
            for f in ((ps.architect_plan if ps else None) or {}).get(
                "impacted_files", []
            )
            if isinstance(f, dict) and f.get("path")
        }
    )
    try:
        diff = await asyncio.to_thread(get_diff, task.id, repo_path)
    except Exception:
        diff = ""
    await _record_git_push_approval(
        db, task.id, repo_path, files, diff, len(subtasks), agent_name="epic_manager"
    )
    return True


async def _planned_files(epic_id: str, db: AsyncSession) -> list[str]:
    task = await _epic_child(epic_id, db)
    if task is None:
        return []
    ps = (
        await db.execute(select(PipelineState).where(PipelineState.task_id == task.id))
    ).scalar_one_or_none()
    plan = (ps.architect_plan if ps else None) or {}
    return [
        str(f.get("path"))
        for f in plan.get("impacted_files", [])
        if isinstance(f, dict) and f.get("path")
    ]


@router.post("/{epic_id}/approve-plan", dependencies=[Depends(require_daily_budget)])
async def approve_epic_plan(
    epic_id: EpicId,
    user_id: str = Depends(require_approver),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Epic lifecycle (Qoder ORCH-04-103): approve the epic's plan; coding
    then runs from the saved plan (no re-planning)."""
    epic = (
        await db.execute(select(Epic).where(Epic.epic_id == epic_id))
    ).scalar_one_or_none()
    if not epic:
        raise HTTPException(status_code=404, detail=f"Epic {epic_id} not found")
    if epic.status == "pending_policy_approval":
        raise HTTPException(
            status_code=409,
            detail="Protected paths still need policy approval first: "
            + (epic.halt_reason or ""),
        )
    if epic.status != "pending_plan_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Epic is in status {epic.status!r}; must be pending_plan_approval",
        )
    epic.status = "plan_approved"
    epic.halt_reason = None
    await db.commit()
    await publish_event(
        GridironEvent(
            event_type="epic.plan_approved",
            epic_id=epic_id,
            payload={"approved_by": user_id},
            emitted_by="api",
        ),
        db=db,
    )
    asyncio.create_task(_launch_epic_after_plan(epic_id))
    return {"epicId": epic_id, "status": "plan_approved", "approvedBy": user_id}


@router.post("/{epic_id}/reject-plan")
async def reject_epic_plan(
    epic_id: EpicId,
    user_id: str = Depends(require_approver),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reject the epic's plan: the epic and its child task are closed."""
    epic = (
        await db.execute(select(Epic).where(Epic.epic_id == epic_id))
    ).scalar_one_or_none()
    if not epic:
        raise HTTPException(status_code=404, detail=f"Epic {epic_id} not found")
    if epic.status not in ("pending_plan_approval", "pending_policy_approval"):
        raise HTTPException(
            status_code=409,
            detail=f"Epic is in status {epic.status!r}; no plan awaiting approval",
        )
    epic.status = "rejected"
    await db.commit()
    await _close_epic_child(epic_id, db)
    await publish_event(
        GridironEvent(
            event_type="epic.plan_rejected",
            epic_id=epic_id,
            payload={"rejected_by": user_id},
            emitted_by="api",
        ),
        db=db,
    )
    return {"epicId": epic_id, "status": "rejected", "rejectedBy": user_id}


@router.post("/{epic_id}/policy-approval")
async def record_policy_approval(
    epic_id: EpicId,
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

    # Epic lifecycle (SEC-05-102): once every blocking rule matching the plan
    # is approved, the plan moves on to plan approval.
    epic = (
        await db.execute(select(Epic).where(Epic.epic_id == epic_id))
    ).scalar_one_or_none()
    if epic is not None and epic.status == "pending_policy_approval":
        from app.agents.manager import _epic_policy_blocks

        remaining = await _epic_policy_blocks(
            await _planned_files(epic_id, db), epic_id, db
        )
        if not remaining:
            epic.status = "pending_plan_approval"
            epic.halt_reason = None
            await db.commit()

    return {
        "approvalId": approval.id,
        "policyId": body.policy_id,
        "epicId": epic_id,
        "decision": body.decision,
        "approvedBy": user_id,
    }


# ---- Background task ----


async def _launch_epic_manager(epic_id: str, goal: str) -> None:
    """Fire-and-forget: run the epic manager pipeline.

    Stage 4 Cluster R Phase 2 (2026-08-05, CLUSTER_R_DESIGN.md §3/§6):
    re-loads the epic (eager-loading .repo, mirroring get_task()'s own
    selectinload(DevTask.repo)) to resolve its real repo_id/repo_path
    before invoking the graph — the epic was already committed with its
    repo_id by create_epic()/approve_epic_cost() before either call site
    schedules this task, so a fresh read here is the single source of
    truth, not a second one.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db.models import Epic
    from app.db.repository import resolve_epic_repo_path
    from app.db.session import get_async_session
    from app.agents.manager import run_epic_manager

    try:
        async with get_async_session() as db:
            result = await db.execute(
                select(Epic)
                .options(selectinload(Epic.repo))
                .where(Epic.epic_id == epic_id)
            )
            epic = result.scalar_one_or_none()
            repo_id = epic.repo_id if epic is not None else None
            repo_path = resolve_epic_repo_path(epic) if epic is not None else None
            created_by = epic.created_by if epic is not None else None
            await run_epic_manager(
                epic_id=epic_id,
                goal=goal,
                db=db,
                repo_id=repo_id,
                repo_path=repo_path,
                created_by=created_by,
            )
    except Exception as exc:
        logger.exception("Epic manager pipeline failed for epic %s", epic_id)
        # Qoder cross-check ORCH-04-108 (2026-10-02): the epic stayed in
        # whatever status the last node set (pending/planning/coding) with
        # no halt_reason, and no endpoint accepts those statuses — stuck for
        # good. "halted" is visible and can be rejected (or re-reviewed).
        try:
            from sqlalchemy import update

            async with get_async_session() as db2:
                await db2.execute(
                    update(Epic)
                    .where(Epic.epic_id == epic_id)
                    .where(Epic.status.in_(["pending", "planning", "coding"]))
                    .values(
                        status="halted",
                        halt_reason=f"Epic pipeline failed: {type(exc).__name__}: {exc}"[
                            :2000
                        ],
                    )
                )
                await db2.commit()
        except Exception:
            logger.warning("Could not mark epic %s halted", epic_id, exc_info=True)


async def _launch_epic_after_plan(epic_id: str) -> None:
    """Fire-and-forget: coding + finalize for an epic whose plan was approved.
    A crash marks the epic halted (same as _launch_epic_manager)."""
    from app.agents.manager import run_epic_after_plan_approval
    from app.db.session import get_async_session

    try:
        async with get_async_session() as db:
            epic = (
                await db.execute(
                    select(Epic)
                    .options(selectinload(Epic.repo))
                    .where(Epic.epic_id == epic_id)
                )
            ).scalar_one()
            await run_epic_after_plan_approval(
                epic_id,
                db,
                repo_path=resolve_epic_repo_path(epic),
                repo_id=epic.repo_id,
            )
    except Exception as exc:
        logger.exception("Epic coding after plan approval failed for %s", epic_id)
        try:
            from sqlalchemy import update

            async with get_async_session() as db2:
                await db2.execute(
                    update(Epic)
                    .where(Epic.epic_id == epic_id)
                    .where(Epic.status.in_(["plan_approved", "coding"]))
                    .values(
                        status="halted",
                        halt_reason=f"Epic coding failed: {type(exc).__name__}: {exc}"[
                            :2000
                        ],
                    )
                )
                await db2.commit()
        except Exception:
            logger.warning("Could not mark epic %s halted", epic_id, exc_info=True)
