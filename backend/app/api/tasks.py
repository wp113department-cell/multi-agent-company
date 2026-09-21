from typing import Any, Literal
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.repository import (
    TransitionError,
    append_log,
    create_task,
    create_task_image,
    delete_task_image,
    get_task,
    get_task_image,
    get_pipeline_state,
    list_logs,
    list_subtasks,
    list_task_images,
    list_tasks,
    repeat_task,
    transition_task,
    get_or_create_pipeline_state,
    resolve_task_repo_path,
)
from app.config import get_settings
from app.middleware.idempotency import get_cached_response, store_response
from app.middleware.rbac import require_approver, require_authenticated
from app.pipeline.queue_adapter import dispatch_job
from app.rate_limit import limiter
from app.repo_tools.worktree import remove_worktree

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _clear_stale_abort(task_id: int) -> None:
    """A new run is starting: any abort flag left by an earlier Stop/Cancel
    belongs to the PREVIOUS run (see ActivityStreamRegistry.clear_abort)."""
    try:
        from app.services.activity_stream import get_activity_registry

        get_activity_registry().clear_abort(task_id)
    except Exception:  # never let flag housekeeping block starting a run
        pass


class CreateTaskRequest(BaseModel):
    title: str
    description: str
    repo_id: int | None = None
    # Stage 4 Tier 3 (2026-08-05, answer2.md Q2) — was a bare `str`, meaning
    # any value (typos, empty string, arbitrary garbage) reached the DB
    # unchecked. Rejected here at the real API boundary (a real 422, not a
    # silently-stored bad value) — migration 027 adds a matching DB CHECK
    # constraint for any write path that bypasses this endpoint.
    priority: Literal["low", "medium", "high"] = "medium"
    project: str | None = None
    # AUDIT_Q_BATCH16 §86 gap-closure (2026-08-11) — real cross-task
    # dependency IDs (other dev_tasks.id values); enforced by /run below.
    depends_on: list[int] | None = None


class TransitionRequest(BaseModel):
    status: str


class PriorityRequest(BaseModel):
    priority: Literal["low", "medium", "high"]


class LogRequest(BaseModel):
    category: str
    message: str
    extra_data: dict[str, Any] | None = None


class RejectRequest(BaseModel):
    reason: str | None = None


class RunRequest(BaseModel):
    mode: str | None = (
        None  # "full" | "simple" — overrides PIPELINE_MODE env for this request
    )


class RepeatTaskRequest(BaseModel):
    # AUDIT_Q_BATCH18 §51 gap-closure — all optional: an unmodified repeat
    # clones title/description/priority from the source task exactly (the
    # deterministic "the same one as yesterday" case the audit named).
    title: str | None = None
    description: str | None = None
    priority: Literal["low", "medium", "high"] | None = None
    mode: str | None = None  # same "full" | "simple" override as RunRequest


def _log_to_dict(log: Any) -> dict[str, Any]:
    return {
        "logId": log.id,
        "taskId": log.task_id,
        "category": log.category,
        "message": log.message,
        "extraData": log.extra_data,
        # AUDIT_Q_BATCH13 §44 gap-closure (2026-08-11) — surface task_logs.rationale
        "rationale": log.rationale,
        "createdAt": log.created_at.isoformat() if log.created_at else None,
    }


def _task_to_dict(task: Any, logs: list[Any] | None = None) -> dict[str, Any]:
    repo = getattr(task, "repo", None)
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "plan": task.plan,
        "diff": task.diff,
        "filesTouched": task.files_touched or [],
        "project": task.project,
        "priority": task.priority,
        "dependsOn": list(task.depends_on or []),
        "assignedAgent": task.assigned_agent,
        "finalSummary": task.final_summary,
        "repoId": task.repo_id,
        "repoName": repo.name if repo else None,
        "repeatedFromTaskId": task.repeated_from_task_id,
        "createdAt": task.created_at.isoformat() if task.created_at else None,
        "updatedAt": task.updated_at.isoformat() if task.updated_at else None,
        "logs": [_log_to_dict(lg) for lg in (logs or [])],
    }


@router.post("", status_code=201)
@limiter.limit(get_settings().rate_limit_tasks)
async def create(
    request: Request,
    body: CreateTaskRequest,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    # AUDIT_Q_BATCH08 §66 "Idempotency" — a client retrying task creation
    # after a dropped response (e.g. a network timeout on a request that
    # actually already succeeded) previously always created a second,
    # duplicate task row. An Idempotency-Key header makes a retried call
    # return the original created task instead.
    cached = await get_cached_response(db, request, "create_task")
    if cached is not None:
        return cached

    task = await create_task(
        db,
        body.title,
        body.description,
        repo_id=body.repo_id,
        priority=body.priority,
        project=body.project,
        depends_on=body.depends_on,
    )
    result = _task_to_dict(task)
    await store_response(db, request, "create_task", result)
    return result


@router.get("")
async def list_all(
    status: str | None = Query(None),
    repo_id: int | None = Query(None),
    cursor: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    tasks, next_cursor = await list_tasks(
        db, status=status, repo_id=repo_id, cursor=cursor, limit=limit
    )
    return {"tasks": [_task_to_dict(t) for t in tasks], "nextCursor": next_cursor}


@router.get("/{task_id}")
async def get_one(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    logs = await list_logs(db, task_id)
    return _task_to_dict(task, logs=logs)


@router.patch("/{task_id}")
async def patch_status(
    task_id: int,
    body: TransitionRequest,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    try:
        task = await transition_task(db, task_id, body.status)
    except TransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _task_to_dict(task)


@router.patch("/{task_id}/priority")
async def patch_priority(
    task_id: int,
    body: PriorityRequest,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """AUDIT_Q_BATCH16 §86 gap-closure (2026-08-11) — "Reorder": neither
    queue adapter supports true in-place reordering of an already-enqueued
    job (AsyncioQueueAdapter's asyncio.Queue is strict FIFO; RQ has no
    built-in live-reprioritization primitive either), so a literal "move
    this job ahead of that one in a live queue" API is not implementable
    without replacing the queue's own data structure — a materially bigger,
    separate architectural decision than this gap-closure pass, matching
    this codebase's own established bar for what counts as "wiring" vs.
    "new capability" (see queue_adapter.py's module docstring on the
    BackgroundTasks-vs-RQ dispatch decision for the precedent).

    What is real and implementable: DevTask.priority is the actual signal
    both PrioritySemaphore (app/pipeline/concurrency.py) and RQQueueAdapter's
    queue selection (gridiron-high vs gridiron-default) read at dispatch
    time — changing it here changes where this task's *next* dispatch
    (waiting subtask/agent-run slot acquisition, or a not-yet-enqueued RQ
    job) lands relative to other tasks, which is the real, honest scope of
    "reorder" for a priority-bucketed scheduler rather than a literal
    linked-list queue. Refused once the task has reached a terminal status —
    changing the priority of already-finished work has no real effect and
    would be a silently-ignored no-op otherwise.
    """
    from app.db.models import VALID_TRANSITIONS, DevTask
    from sqlalchemy import update

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    terminal_statuses = frozenset(
        status for status, targets in VALID_TRANSITIONS.items() if not targets
    )
    if task.status in terminal_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"Task {task_id} is {task.status!r} — priority can no "
            "longer affect its dispatch order.",
        )

    await db.execute(
        update(DevTask).where(DevTask.id == task_id).values(priority=body.priority)
    )
    await db.commit()
    await append_log(
        db,
        task_id,
        "priority",
        f"Priority changed to {body.priority!r}",
    )
    task = await get_task(db, task_id)
    return _task_to_dict(task)


@router.post("/{task_id}/logs", status_code=201)
async def add_log(
    task_id: int,
    body: LogRequest,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    log = await append_log(db, task_id, body.category, body.message, body.extra_data)
    return _log_to_dict(log)


@router.get("/{task_id}/logs")
async def get_logs(
    task_id: int,
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    logs = await list_logs(db, task_id, include_archived=include_archived)
    return {"logs": [_log_to_dict(lg) for lg in logs]}


@router.post("/{task_id}/run")
@limiter.limit(get_settings().rate_limit_tasks)
async def run_task(
    request: Request,
    task_id: int,
    body: RunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """Trigger planning pipeline or simple planner for a pending/blocked/rejected task."""
    from app.api.agents import launch_planning_pipeline, launch_planner

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in ("pending", "rejected", "blocked"):
        raise HTTPException(
            status_code=400, detail=f"Cannot start planning from status {task.status!r}"
        )

    # AUDIT_Q_BATCH16 §86 gap-closure (2026-08-11) — "Detect dependencies /
    # optimize order" (org-wide): the one real place a DevTask enters its
    # pipeline, refusing to start until every declared dependency has
    # actually reached "completed". Not a background scheduler that
    # auto-dispatches once deps clear (a materially bigger, separate
    # decision — see PriorityRequest's own docstring for the same framing
    # on "Reorder") — a real, honest, human/caller-triggered dependency
    # gate: the caller retries /run once the dependency finishes, exactly
    # like the existing "blocked" status already requires a human/caller
    # to re-trigger.
    if task.depends_on:
        unmet: list[int] = []
        for dep_id in task.depends_on:
            dep_task = await get_task(db, int(dep_id))
            if dep_task is None or dep_task.status != "completed":
                unmet.append(int(dep_id))
        if unmet:
            raise HTTPException(
                status_code=409,
                detail=f"Task {task_id} depends on task(s) {unmet} which have "
                "not reached 'completed' yet.",
            )

    # Resolve which repo path agents should use for this task
    repo_path = resolve_task_repo_path(task)

    await transition_task(db, task_id, "planning")
    await append_log(db, task_id, "pipeline", "Planning triggered")

    settings = get_settings()
    mode = body.mode or settings.pipeline_mode

    if mode == "full":
        _clear_stale_abort(task_id)
        await dispatch_job(
            background_tasks,
            launch_planning_pipeline,
            task_id,
            str(task.title),
            str(task.description),
            repo_path,
            priority=task.priority,
        )
    else:
        _clear_stale_abort(task_id)
        await dispatch_job(
            background_tasks,
            launch_planner,
            task_id,
            str(task.title),
            str(task.description),
            repo_path,
            priority=task.priority,
        )

    return {"triggered": True, "mode": mode}


@router.post("/{task_id}/restart")
@limiter.limit(get_settings().rate_limit_tasks)
async def restart_task(
    request: Request,
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """Reset a failed/blocked/error task back to pending and re-trigger the planning pipeline."""
    from app.api.agents import launch_planning_pipeline
    from app.db.models import DevTask
    from sqlalchemy import update

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Gap-closure (Audit 04 fix, ORCH-04-004): restart previously force-reset
    # status regardless of current state, with no check for whether a
    # background pipeline run (launch_planning_pipeline/launch_manager/
    # launch_coder/launch_planner) was already actively running for this
    # task_id — a double-dispatch race against the same worktree. Those are
    # the only statuses ever set at the START of an in-flight background
    # task and held until it reaches a terminal-ish status itself, so they
    # reliably signal "something is still running" without needing a new
    # lock/column.
    _ACTIVE_STATUSES = ("planning", "coding", "testing")
    if task.status in _ACTIVE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Task {task_id} has an active pipeline run in progress "
                f"(status={task.status!r}) — wait for it to reach a "
                "terminal-ish status (ready_for_review/blocked/failed/"
                "rejected) before restarting."
            ),
        )

    # Force-reset to pending regardless of current status
    await db.execute(
        update(DevTask).where(DevTask.id == task_id).values(status="pending")
    )
    await db.commit()

    # Re-fetch to get fresh state for the pipeline
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found after reset")

    repo_path = resolve_task_repo_path(task)

    await transition_task(db, task_id, "planning")
    await append_log(
        db, task_id, "pipeline", "Task restarted — planning pipeline re-triggered"
    )

    _clear_stale_abort(task_id)
    await dispatch_job(
        background_tasks,
        launch_planning_pipeline,
        task_id,
        str(task.title),
        str(task.description),
        repo_path,
        priority=task.priority,
    )

    return {"restarted": True, "taskId": task_id}


@router.post("/{task_id}/repeat", status_code=201)
@limiter.limit(get_settings().rate_limit_tasks)
async def repeat(
    request: Request,
    task_id: int,
    body: RepeatTaskRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """AUDIT_Q_BATCH18 §51 gap-closure (2026-08-12) — "Repeat Task &
    Historical Context" was PARTIAL: the only recall mechanism was
    memory_hook_node's implicit semantic-similarity retrieval, with no way
    to say "the same one as yesterday" and have it resolved
    deterministically. This is that deterministic path: clones `task_id`
    (any status — a completed/closed task is the normal case, "run this
    again", but nothing requires it) into a brand-new DevTask via
    repeat_task() (repeated_from_task_id set to the real source id, not a
    similarity guess) and immediately dispatches it through the exact same
    planning-pipeline path POST /{task_id}/run uses — a repeat that only
    created a DB row without actually running would be "clone", not
    "repeat".
    """
    from app.api.agents import launch_planning_pipeline, launch_planner

    source = await get_task(db, task_id)
    if not source:
        raise HTTPException(status_code=404, detail="Task not found")

    new_task = await repeat_task(
        db,
        source,
        title=body.title,
        description=body.description,
        priority=body.priority,
    )

    repo_path = resolve_task_repo_path(new_task)
    await transition_task(db, new_task.id, "planning")
    await append_log(
        db,
        new_task.id,
        "pipeline",
        f"Task repeated from #{task_id} — planning pipeline triggered",
    )

    settings = get_settings()
    mode = body.mode or settings.pipeline_mode
    if mode == "full":
        _clear_stale_abort(task_id)
        await dispatch_job(
            background_tasks,
            launch_planning_pipeline,
            new_task.id,
            str(new_task.title),
            str(new_task.description),
            repo_path,
            priority=new_task.priority,
        )
    else:
        _clear_stale_abort(task_id)
        await dispatch_job(
            background_tasks,
            launch_planner,
            new_task.id,
            str(new_task.title),
            str(new_task.description),
            repo_path,
            priority=new_task.priority,
        )

    return {
        "repeated": True,
        "sourceTaskId": task_id,
        "taskId": new_task.id,
        "task": _task_to_dict(new_task),
    }


@router.post("/{task_id}/approve")
async def approve_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Approve diff after coding — start coder or mark completed."""
    from app.api.agents import launch_coder

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "ready_for_review":
        raise HTTPException(
            status_code=400,
            detail=f"Task must be ready_for_review, got {task.status!r}",
        )
    # Gap-closure (Audit 04 fix, ORCH-04-002): "ready_for_review" is reused
    # for two different real states — "plan ready, awaiting approval to
    # start coding" (task.diff is still None) and "code diff ready for
    # final review" (task.diff was already set by a prior coding run).
    # Without this check, re-clicking "Approve" on an already-coded task
    # silently re-launches the coder from scratch instead of being a no-op
    # or a clear error — task.diff's presence is the same signal
    # POST /{task_id}/complete uses below.
    if task.diff is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Task already has a diff — coding already completed once. "
                "Nothing to approve here; use POST /{task_id}/complete or "
                "the git-push flow instead of re-approving."
            ),
        )

    # Gap-closure (Days 11-15 audit, 2026-07-22): this endpoint never resolved
    # the task's assigned repo (task.repo_id), unlike /run, /restart, and
    # /pipeline/approve — launch_coder silently fell back to the single
    # global active repo, ignoring per-task repo selection entirely.
    repo_path = resolve_task_repo_path(task)

    plan = str(task.plan or "")
    task = await transition_task(db, task_id, "coding")
    await append_log(db, task_id, "approval", "Plan approved — coding agent starting")

    _clear_stale_abort(task_id)
    await dispatch_job(
        background_tasks,
        launch_coder,
        task_id,
        plan,
        repo_path,
        priority=task.priority,
    )
    return {"approved": True, "task": _task_to_dict(task)}


@router.post("/{task_id}/reject")
async def reject_task(
    task_id: int,
    body: RejectRequest,
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    from app.db.models import Repo
    from sqlalchemy import select

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = await transition_task(db, task_id, "rejected")
    msg = f"Task rejected. Reason: {body.reason}" if body.reason else "Task rejected"
    await append_log(db, task_id, "rejection", msg)

    # Gap-closure (Audit 04 fix, ORCH-04-012): the worktree is no longer
    # needed once a task is rejected (whether the plan or an already-coded
    # diff) — remove_worktree() previously had zero real callers anywhere,
    # so worktrees accumulated forever. Best-effort: usually a no-op if
    # coding never started (no worktree exists yet for a rejected plan).
    try:
        repo_path: str | None = None
        if task.repo_id:
            result = await db.execute(select(Repo).where(Repo.id == task.repo_id))
            repo_obj = result.scalar_one_or_none()
            if repo_obj:
                repo_path = repo_obj.local_path
        remove_worktree(task_id, repo_path)
    except Exception:
        pass

    return {"rejected": True, "task": _task_to_dict(task)}


@router.post("/{task_id}/pipeline/approve")
async def pipeline_approve(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Resume the LangGraph pipeline with approval → launch coder."""
    from app.api.agents import resume_planning_pipeline
    from app.db.models import Repo
    from sqlalchemy import select

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    ps = await get_or_create_pipeline_state(db, task_id)
    if ps.stage != "awaiting_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Pipeline is not awaiting approval (stage={ps.stage!r})",
        )

    repo_path: str | None = None
    if task.repo_id:
        result = await db.execute(select(Repo).where(Repo.id == task.repo_id))
        repo_obj = result.scalar_one_or_none()
        if repo_obj and repo_obj.status == "ready":
            repo_path = repo_obj.local_path

    await append_log(db, task_id, "approval", "Plan approved — resuming pipeline")
    _clear_stale_abort(task_id)
    await dispatch_job(
        background_tasks,
        resume_planning_pipeline,
        task_id,
        True,
        repo_path,
        priority=task.priority,
    )
    return {"approved": True}


@router.post("/{task_id}/pipeline/reject")
async def pipeline_reject(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Resume the LangGraph pipeline with rejection."""
    from app.api.agents import resume_planning_pipeline

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    ps = await get_or_create_pipeline_state(db, task_id)
    if ps.stage != "awaiting_approval":
        raise HTTPException(
            status_code=400,
            detail=f"Pipeline is not awaiting approval (stage={ps.stage!r})",
        )

    await append_log(db, task_id, "rejection", "Plan rejected — pipeline cancelled")
    _clear_stale_abort(task_id)
    await dispatch_job(
        background_tasks,
        resume_planning_pipeline,
        task_id,
        False,
        priority=task.priority,
    )
    return {"rejected": True}


@router.get("/{task_id}/subtasks")
async def get_subtasks(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    subtasks = await list_subtasks(db, task_id)
    return {
        "subtasks": [
            {
                "id": s.id,
                "type": s.type,
                "title": s.title,
                "description": s.description,
                "filesToEdit": s.files_to_edit,
                "dependsOn": s.depends_on,
                "status": s.status,
            }
            for s in subtasks
        ]
    }


@router.get("/{task_id}/pipeline")
async def get_pipeline(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    ps = await get_pipeline_state(db, task_id)
    if ps is None:
        raise HTTPException(status_code=404, detail="No pipeline state for this task")
    return {
        "taskId": task_id,
        "stage": ps.stage,
        "pmBrief": ps.pm_brief,
        "architectPlan": ps.architect_plan,
        "subtasks": ps.subtasks_json,
        "approved": ps.approved,
    }


def _synthesize_explanation(
    task: Any,
    goals: list[str] | None,
    technical_approach: str | None,
    risk_level: str | None,
    dispatch_rationales: list[str],
) -> str:
    """AUDIT_Q_BATCH13 §44 gap-closure (2026-08-11) — "explain why this
    approach / these agents / these tools were chosen". Assembles real,
    already-persisted data (PM brief goals, architect_plan's technical
    approach, and FleetManager.select()'s own DispatchPlan.reason strings,
    now stored via task_logs.rationale) into one coherent, plain-language
    explanation, instead of requiring a user to reconstruct it from raw
    activity_stream events themselves. Never invents content: a section is
    omitted, not guessed, when the underlying data doesn't exist yet."""
    parts = [f"Task {task.id} ({task.status}): {task.title}."]
    if goals:
        parts.append("Goals identified by the PM agent: " + "; ".join(goals[:5]) + ".")
    if technical_approach:
        approach_line = (
            f"Technical approach chosen by the architect agent: {technical_approach}"
        )
        if risk_level:
            approach_line += f" (risk level: {risk_level})"
        parts.append(approach_line + ".")
    if dispatch_rationales:
        parts.append(
            "Agent selection: " + " ".join(f"{r}." for r in dispatch_rationales)
        )
    if len(parts) == 1:
        parts.append(
            "No structured planning or agent-dispatch rationale has been "
            "recorded for this task yet."
        )
    return " ".join(parts)


@router.get("/{task_id}/explain")
async def explain_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """Synthesized, human-readable explanation of why this task's plan and
    agent dispatch decisions were made — see _synthesize_explanation()."""
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    logs = await list_logs(db, task_id)
    ps = await get_pipeline_state(db, task_id)

    pm_brief = ps.pm_brief if ps and ps.pm_brief else {}
    architect_plan = ps.architect_plan if ps and ps.architect_plan else {}
    goals = pm_brief.get("goals") if isinstance(pm_brief, dict) else None
    plan_confidence = pm_brief.get("confidence") if isinstance(pm_brief, dict) else None
    technical_approach = (
        architect_plan.get("technical_approach")
        if isinstance(architect_plan, dict)
        else None
    )
    risk_level = (
        architect_plan.get("risk_level") if isinstance(architect_plan, dict) else None
    )

    dispatch_decisions = [
        {
            "message": lg.message,
            "rationale": lg.rationale,
            "createdAt": lg.created_at.isoformat() if lg.created_at else None,
        }
        for lg in logs
        if lg.rationale
    ]

    explanation = _synthesize_explanation(
        task,
        goals if isinstance(goals, list) else None,
        technical_approach,
        risk_level,
        [d["rationale"] for d in dispatch_decisions if d["rationale"]],
    )

    return {
        "taskId": task_id,
        "status": task.status,
        "goals": goals,
        "planConfidence": plan_confidence,
        "technicalApproach": technical_approach,
        "riskLevel": risk_level,
        "agentDispatchDecisions": dispatch_decisions,
        "explanation": explanation,
    }


@router.get("/{task_id}/diff")
async def get_diff(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"diff": task.diff, "filesTouched": task.files_touched or []}


@router.post("/{task_id}/complete")
async def complete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Gap-closure (Audit 04 fix, ORCH-04-002). Manually close out a task
    that has a real diff ready and no further action expected — the
    counterpart to the automatic completion dispatch_git_push_decision()
    performs on a successful push, for tasks with no GitHub-linked repo
    (simple mode has no push flow at all; full mode without a linked repo
    never gets a push approval either). Requires the *coded*
    ready_for_review (task.diff already set), not the *plan* one — the same
    signal approve_task's idempotency check above uses."""
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "ready_for_review":
        raise HTTPException(
            status_code=400,
            detail=f"Task must be ready_for_review, got {task.status!r}",
        )
    if task.diff is None:
        raise HTTPException(
            status_code=400,
            detail="Task has no diff yet — coding hasn't completed.",
        )
    task = await transition_task(db, task_id, "completed")
    await append_log(db, task_id, "completion", "Task marked completed")

    # Gap-closure (Audit 04 fix, ORCH-04-012): worktree no longer needed
    # once a task is completed. Best-effort.
    try:
        from app.db.models import Repo
        from sqlalchemy import select

        repo_path: str | None = None
        if task.repo_id:
            result = await db.execute(select(Repo).where(Repo.id == task.repo_id))
            repo_obj = result.scalar_one_or_none()
            if repo_obj:
                repo_path = repo_obj.local_path
        remove_worktree(task_id, repo_path)
    except Exception:
        pass

    return {"completed": True, "task": _task_to_dict(task)}


@router.get("/{task_id}/pr")
async def get_pr(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """Day 14 — Git Push Workflow."""
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "branchName": task.branch_name,
        "prUrl": task.pr_url,
        "prStatus": task.pr_status,
    }


@router.post("/{task_id}/push")
async def push_task(
    task_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _approver: str = Depends(require_approver),
) -> dict[str, Any]:
    """Day 14 — Git Push Workflow. Manual retry: re-runs push+PR creation
    directly, bypassing the approval gate since approval already happened
    once for a previously-approved push that failed transiently.

    AUDIT_Q_BATCH08 §66 "Idempotency" — a real git push/PR creation is
    exactly the "write_remote" hazard class app/agents/base_graph.py's own
    `_RETRY_EXCLUDED_PERMISSIONS` documents ("a network call that appears to
    fail may have already succeeded remotely — blindly retrying risks a
    real, visible duplicate side effect"): a client retrying this endpoint
    after a timeout (with no idea whether the first request's dispatch
    already went through) previously had no way to avoid double-triggering
    a push. An `Idempotency-Key` header now makes a retried call return the
    original trigger response instead of dispatching a second time.
    """
    from app.api.approvals import dispatch_git_push_decision

    cached = await get_cached_response(db, request, "push_task")
    if cached is not None:
        return cached

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.branch_name is None:
        raise HTTPException(
            status_code=400,
            detail="Task has no branch to push — has coding completed yet?",
        )

    _clear_stale_abort(task_id)
    await dispatch_job(
        background_tasks,
        dispatch_git_push_decision,
        task_id,
        True,
        priority=task.priority,
    )
    result = {"triggered": True, "taskId": task_id}
    await store_response(db, request, "push_task", result)
    return result


# ---------------------------------------------------------------------------
# PDF attachment extraction — POST /api/tasks/extract-pdfs
# Up to 5 PDF files; returns extracted text from each.
# ---------------------------------------------------------------------------

MAX_PDF_FILES = 5
MAX_PDF_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB per file


@router.post("/extract-pdfs")
async def extract_pdfs(
    files: list[UploadFile] = File(...),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """Extract text from up to 5 PDF files. Returns extracted text for each file.

    The caller can then append this text to the task description before submitting.
    """
    if len(files) > MAX_PDF_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_PDF_FILES} PDF files allowed. Got {len(files)}.",
        )

    results = []
    for upload in files:
        fname = upload.filename or "file.pdf"
        if not fname.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"'{fname}' is not a PDF file.")

        raw = await upload.read()
        if len(raw) > MAX_PDF_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"'{fname}' exceeds 20 MB limit ({len(raw) // 1024 // 1024} MB).",
            )

        text = _extract_pdf_text(raw, fname)
        results.append({"filename": fname, "text": text, "chars": len(text)})

    return {"ok": True, "files": results}


def _extract_pdf_text(raw: bytes, fname: str) -> str:
    """Extract plain text from PDF bytes using pdfplumber."""
    try:
        import io
        import pdfplumber

        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            pages = []
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages.append(f"[Page {i + 1}]\n{page_text}")
            return "\n\n".join(pages)
    except Exception as exc:
        return f"[Could not extract text from '{fname}': {exc}]"


# ---------------------------------------------------------------------------
# Day 16 — Image Input Pipeline. Reference images (e.g. a website design
# screenshot), injected as Anthropic ImageBlockParam content blocks into
# pm/architect/frontend_dev/reviewer's initial calls. Limits per REPO-FIRST
# research (roo-code's DEFAULT_MAX_IMAGE_FILE_SIZE_MB/DEFAULT_MAX_TOTAL_IMAGE_SIZE_MB/
# MAX_IMAGES_PER_MESSAGE) — same shape as the extract-pdfs section above.
# Format allowlist matches the Anthropic Messages API's actual supported
# vision media types exactly (not a superset like roo-code's local-file list,
# which also covers formats the API itself would reject).
# ---------------------------------------------------------------------------

MAX_IMAGES_PER_TASK = 20
MAX_IMAGE_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB per file
MAX_TOTAL_IMAGE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB total per task

_IMAGE_EXT_TO_MEDIA_TYPE = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _image_media_type(filename: str) -> str | None:
    import os

    ext = os.path.splitext(filename.lower())[1]
    return _IMAGE_EXT_TO_MEDIA_TYPE.get(ext)


@router.post("/{task_id}/images")
async def upload_task_images(
    task_id: int,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """Upload reference images for a task (e.g. a website design screenshot).
    Multipart, same shape as /extract-pdfs. Per-file 5MB limit, 20MB total
    across the task's existing + new images, max 20 images per task."""
    import base64

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    existing = await list_task_images(db, task_id)
    if len(existing) + len(files) > MAX_IMAGES_PER_TASK:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_IMAGES_PER_TASK} images per task "
            f"(already have {len(existing)}, uploading {len(files)}).",
        )

    total_bytes = sum(len(base64.b64decode(img.base64_data)) for img in existing)
    next_order = max((img.display_order for img in existing), default=-1) + 1

    created = []
    for upload in files:
        fname = upload.filename or "image"
        media_type = _image_media_type(fname)
        if media_type is None:
            raise HTTPException(
                status_code=400,
                detail=f"'{fname}' is not a supported image format "
                "(png, jpg, jpeg, gif, webp).",
            )

        raw = await upload.read()
        if len(raw) > MAX_IMAGE_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"'{fname}' exceeds 5 MB limit ({len(raw) // 1024 // 1024} MB).",
            )
        total_bytes += len(raw)
        if total_bytes > MAX_TOTAL_IMAGE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Total image size exceeds 20 MB limit at '{fname}'.",
            )

        b64 = base64.b64encode(raw).decode("ascii")
        image = await create_task_image(db, task_id, b64, media_type, next_order)
        next_order += 1
        created.append(
            {"id": image.id, "mimeType": image.mime_type, "order": image.display_order}
        )

    return {"created": created}


@router.get("/{task_id}/images")
async def get_task_images(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """Metadata only (id/mimeType/order) — never the base64 blob, to keep this
    poll-friendly. Use GET /{task_id}/images/{image_id} for the raw bytes."""
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    images = await list_task_images(db, task_id)
    return {
        "images": [
            {
                "id": img.id,
                "mimeType": img.mime_type,
                "order": img.display_order,
                "createdAt": img.created_at.isoformat(),
            }
            for img in images
        ]
    }


@router.get("/{task_id}/images/{image_id}")
async def get_task_image_bytes(
    task_id: int,
    image_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> Response:
    """Raw image bytes with the correct Content-Type — for <img src=...>."""
    import base64

    image = await get_task_image(db, image_id)
    if not image or image.task_id != task_id:
        raise HTTPException(status_code=404, detail="Image not found")

    return Response(
        content=base64.b64decode(image.base64_data), media_type=image.mime_type
    )


@router.delete("/{task_id}/images/{image_id}")
async def remove_task_image(
    task_id: int,
    image_id: int,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    image = await get_task_image(db, image_id)
    if not image or image.task_id != task_id:
        raise HTTPException(status_code=404, detail="Image not found")

    deleted = await delete_task_image(db, image_id)
    return {"deleted": deleted}
