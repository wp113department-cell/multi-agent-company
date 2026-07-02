from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.repository import (
    TransitionError,
    append_log,
    create_task,
    get_task,
    list_logs,
    list_subtasks,
    list_tasks,
    transition_task,
    get_or_create_pipeline_state,
)
from app.config import get_settings

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class CreateTaskRequest(BaseModel):
    title: str
    description: str


class TransitionRequest(BaseModel):
    status: str


class LogRequest(BaseModel):
    category: str
    message: str
    extra_data: dict[str, Any] | None = None


class RejectRequest(BaseModel):
    reason: str | None = None


def _task_to_dict(task: Any) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "plan": task.plan,
        "diff": task.diff,
        "files_touched": task.files_touched,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


@router.post("", status_code=201)
async def create(body: CreateTaskRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    task = await create_task(db, body.title, body.description)
    return _task_to_dict(task)


@router.get("")
async def list_all(
    status: str | None = Query(None),
    cursor: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tasks, next_cursor = await list_tasks(db, status=status, cursor=cursor, limit=limit)
    return {"tasks": [_task_to_dict(t) for t in tasks], "nextCursor": next_cursor}


@router.get("/{task_id}")
async def get_one(task_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_to_dict(task)


@router.patch("/{task_id}")
async def patch_status(task_id: int, body: TransitionRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        task = await transition_task(db, task_id, body.status)
    except TransitionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _task_to_dict(task)


@router.post("/{task_id}/logs", status_code=201)
async def add_log(task_id: int, body: LogRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    log = await append_log(db, task_id, body.category, body.message, body.extra_data)
    return {
        "id": log.id,
        "task_id": log.task_id,
        "category": log.category,
        "message": log.message,
        "extra_data": log.extra_data,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


@router.get("/{task_id}/logs")
async def get_logs(task_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    logs = await list_logs(db, task_id)
    return {
        "logs": [
            {
                "id": l.id,
                "category": l.category,
                "message": l.message,
                "extra_data": l.extra_data,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ]
    }


@router.post("/{task_id}/run")
async def run_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Trigger the planning pipeline for a pending/blocked/rejected task."""
    from app.api.agents import launch_planning_pipeline, launch_planner

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in ("pending", "rejected", "blocked"):
        raise HTTPException(status_code=400, detail=f"Cannot start planning from status {task.status!r}")

    await transition_task(db, task_id, "planning")
    await append_log(db, task_id, "pipeline", "Planning triggered")

    settings = get_settings()
    if settings.pipeline_mode == "full":
        background_tasks.add_task(
            launch_planning_pipeline, task_id, str(task.title), str(task.description)
        )
    else:
        background_tasks.add_task(
            launch_planner, task_id, str(task.title), str(task.description)
        )

    return {"triggered": True, "mode": settings.pipeline_mode}


@router.post("/{task_id}/approve")
async def approve_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Approve plan — start coding agent."""
    from app.api.agents import launch_coder

    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "ready_for_review":
        raise HTTPException(status_code=400, detail=f"Task must be ready_for_review, got {task.status!r}")

    plan = str(task.plan or "")
    task = await transition_task(db, task_id, "coding")
    await append_log(db, task_id, "approval", "Plan approved — coding agent starting")

    background_tasks.add_task(launch_coder, task_id, plan)
    return {"approved": True, "task": _task_to_dict(task)}


@router.post("/{task_id}/reject")
async def reject_task(
    task_id: int, body: RejectRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task = await transition_task(db, task_id, "rejected")
    msg = f"Task rejected. Reason: {body.reason}" if body.reason else "Task rejected"
    await append_log(db, task_id, "rejection", msg)
    return {"rejected": True, "task": _task_to_dict(task)}


@router.get("/{task_id}/subtasks")
async def get_subtasks(task_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    subtasks = await list_subtasks(db, task_id)
    return {
        "subtasks": [
            {
                "id": s.id,
                "type": s.type,
                "title": s.title,
                "description": s.description,
                "files_to_edit": s.files_to_edit,
                "depends_on": s.depends_on,
                "status": s.status,
            }
            for s in subtasks
        ]
    }


@router.get("/{task_id}/pipeline")
async def get_pipeline(task_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Return pipeline state for a task."""
    ps = await get_or_create_pipeline_state(db, task_id)
    return {
        "task_id": task_id,
        "stage": ps.stage,
        "pm_brief": ps.pm_brief,
        "architect_plan": ps.architect_plan,
        "subtasks": ps.subtasks_json,
        "approved": ps.approved,
    }


@router.get("/{task_id}/diff")
async def get_diff(task_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    task = await get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"diff": task.diff, "files_touched": task.files_touched}
