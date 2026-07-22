"""Database operations for tasks, logs, agent runs, subtasks, and pipeline state."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    AgentRun,
    DevTask,
    PipelineState,
    Subtask,
    SystemSetting,
    TaskImage,
    TaskLog,
    can_transition,
)


class TransitionError(ValueError):
    pass


async def create_task(
    db: AsyncSession, title: str, description: str, repo_id: int | None = None
) -> DevTask:
    task = DevTask(
        title=title, description=description, status="pending", repo_id=repo_id
    )
    db.add(task)
    await db.commit()
    created = await get_task(db, task.id)
    assert created is not None
    return created


async def get_task(db: AsyncSession, task_id: int) -> DevTask | None:
    result = await db.execute(
        select(DevTask).options(selectinload(DevTask.repo)).where(DevTask.id == task_id)
    )
    return result.scalar_one_or_none()


async def list_tasks(
    db: AsyncSession,
    status: str | None = None,
    repo_id: int | None = None,
    cursor: int | None = None,
    limit: int = 20,
) -> tuple[list[DevTask], int | None]:
    q = select(DevTask).options(selectinload(DevTask.repo)).order_by(DevTask.id.desc())
    if status:
        q = q.where(DevTask.status == status)
    if repo_id is not None:
        q = q.where(DevTask.repo_id == repo_id)
    if cursor is not None:
        q = q.where(DevTask.id < cursor)
    q = q.limit(limit + 1)
    result = await db.execute(q)
    rows: list[DevTask] = list(result.scalars())
    next_cursor: int | None = None
    if len(rows) > limit:
        next_cursor = rows[limit].id
        rows = rows[:limit]
    return rows, next_cursor


async def transition_task(db: AsyncSession, task_id: int, new_status: str) -> DevTask:
    task = await get_task(db, task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")
    if not can_transition(str(task.status), new_status):
        raise TransitionError(
            f"Cannot transition task {task_id} from {task.status!r} to {new_status!r}"
        )
    task.status = new_status
    await db.commit()
    # Re-fetch via get_task so the repo relationship is eagerly loaded (avoids MissingGreenlet)
    refreshed = await get_task(db, task_id)
    assert refreshed is not None
    return refreshed


async def update_task_plan(db: AsyncSession, task_id: int, plan: str) -> None:
    await db.execute(update(DevTask).where(DevTask.id == task_id).values(plan=plan))
    await db.commit()


async def update_task_diff(
    db: AsyncSession, task_id: int, diff: str, files_touched: list[str]
) -> None:
    await db.execute(
        update(DevTask)
        .where(DevTask.id == task_id)
        .values(diff=diff, files_touched=files_touched)
    )
    await db.commit()


async def update_task_branch_name(db: AsyncSession, task_id: int, branch_name: str) -> None:
    """Day 14 — Git Push Workflow. Records the worktree branch (already
    created by worktree.create_worktree(); this just persists the name)."""
    await db.execute(update(DevTask).where(DevTask.id == task_id).values(branch_name=branch_name))
    await db.commit()


async def update_task_pr(
    db: AsyncSession, task_id: int, pr_url: str | None, pr_status: str
) -> None:
    """Day 14 — Git Push Workflow. pr_status: none|pending|pushed|failed."""
    await db.execute(
        update(DevTask).where(DevTask.id == task_id).values(pr_url=pr_url, pr_status=pr_status)
    )
    await db.commit()


async def create_task_image(
    db: AsyncSession,
    task_id: int,
    base64_data: str,
    mime_type: str,
    display_order: int = 0,
) -> TaskImage:
    """Day 16 — Image Input Pipeline."""
    image = TaskImage(
        task_id=task_id,
        base64_data=base64_data,
        mime_type=mime_type,
        display_order=display_order,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)
    return image


async def list_task_images(db: AsyncSession, task_id: int) -> list[TaskImage]:
    """Day 16 — ordered ascending by display_order, then id. Callers that only
    need metadata (id/mimeType/order) should not read .base64_data off these
    rows into an API response — use get_task_image() for the raw-bytes route."""
    result = await db.execute(
        select(TaskImage)
        .where(TaskImage.task_id == task_id)
        .order_by(TaskImage.display_order, TaskImage.id)
    )
    return list(result.scalars().all())


async def get_task_image(db: AsyncSession, image_id: int) -> TaskImage | None:
    return await db.get(TaskImage, image_id)


async def delete_task_image(db: AsyncSession, image_id: int) -> bool:
    result = await db.execute(delete(TaskImage).where(TaskImage.id == image_id))
    await db.commit()
    count: int = getattr(result, "rowcount", 0)  # rowcount available on CursorResult
    return count > 0


async def append_log(
    db: AsyncSession,
    task_id: int,
    category: str,
    message: str,
    extra_data: dict[str, Any] | None = None,
) -> TaskLog:
    log = TaskLog(
        task_id=task_id, category=category, message=message, extra_data=extra_data
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


async def list_logs(db: AsyncSession, task_id: int) -> list[TaskLog]:
    result = await db.execute(
        select(TaskLog).where(TaskLog.task_id == task_id).order_by(TaskLog.created_at)
    )
    return list(result.scalars())


async def create_agent_run(
    db: AsyncSession, task_id: int, agent_type: str, model_id: str
) -> AgentRun:
    run = AgentRun(
        id=str(uuid.uuid4()),
        task_id=task_id,
        agent_type=agent_type,
        status="running",
        model_id=model_id,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def heartbeat_agent_run(db: AsyncSession, run_id: str) -> None:
    await db.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id)
        .values(last_heartbeat_at=datetime.now(timezone.utc).replace(tzinfo=None))
    )
    await db.commit()


async def finish_agent_run(
    db: AsyncSession,
    run_id: str,
    status: str,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_estimate: float | None = None,
    error: str | None = None,
) -> None:
    await db.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id)
        .values(
            status=status,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_estimate=cost_estimate,
            error=error,
            finished_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    await db.commit()


async def save_subtasks(
    db: AsyncSession, task_id: int, subtasks: list[dict[str, Any]]
) -> None:
    for st in subtasks:
        sub = Subtask(
            task_id=task_id,
            type=st.get("type", "backend"),
            title=st["title"],
            description=st.get("description"),
            files_to_edit=st.get("files_to_edit"),
            depends_on=st.get("depends_on"),
        )
        db.add(sub)
    await db.commit()


async def list_subtasks(db: AsyncSession, task_id: int) -> list[Subtask]:
    result = await db.execute(
        select(Subtask).where(Subtask.task_id == task_id).order_by(Subtask.id)
    )
    return list(result.scalars())


async def get_pipeline_state(db: AsyncSession, task_id: int) -> PipelineState | None:
    """Return the pipeline state row if it exists, or None."""
    result = await db.execute(
        select(PipelineState).where(PipelineState.task_id == task_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_pipeline_state(db: AsyncSession, task_id: int) -> PipelineState:
    state = await get_pipeline_state(db, task_id)
    if state is None:
        state = PipelineState(task_id=task_id, stage="pm")
        db.add(state)
        await db.commit()
        await db.refresh(state)
    return state


async def update_pipeline_state(
    db: AsyncSession,
    task_id: int,
    stage: str,
    **kwargs: Any,
) -> PipelineState:
    state = await get_or_create_pipeline_state(db, task_id)
    state.stage = stage
    for k, v in kwargs.items():
        setattr(state, k, v)
    await db.commit()
    await db.refresh(state)
    return state


# ---- System settings ----


async def get_setting(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else None


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    existing = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    row = existing.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))
    await db.commit()
