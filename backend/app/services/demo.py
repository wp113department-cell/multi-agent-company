"""Demo data (client demos, 2026-10-07).

`scripts/seed_demo_data.py` creates realistic projects, tasks, approvals,
improvement suggestions and cost history, all marked with
``created_by = DEMO_CREATOR``. Acting on a DEMO task (Start, Approve plan,
Restart, deciding one of its approvals) must never start real AI work: there
is no real agent run behind it, and it would spend money in front of a
client. Instead the task moves to the next stage of its lifecycle and the
step is written to its timeline. Real tasks are never affected: every hook
checks the marker first and returns False for anything else.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

DEMO_CREATOR = "demo-seed"

_NOTE = "Demo data: no AI was used for this step."

# step message -> what the task's still-waiting decisions become
_DECISION = {
    "Plan approved; coding started": "approved",
    "Plan rejected": "rejected",
    "Changes approved and sent to GitHub": "approved",
    "Sending to GitHub was declined": "rejected",
    "Question answered; work continues": "approved",
    "Question left unanswered": "rejected",
}

_EVENT_SOURCES = {
    "start": ("pending", "rejected", "blocked"),
    "plan_approved": ("ready_for_review",),
    "plan_rejected": ("ready_for_review",),
    "push_approved": ("ready_for_review",),
    "push_rejected": ("ready_for_review",),
    "answered": ("blocked",),
    "declined": ("blocked",),
}


def func_now() -> Any:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


async def is_demo_task(db: AsyncSession, task_id: int | None) -> bool:
    if task_id is None:
        return False
    from app.db.models import DevTask

    task = await db.get(DevTask, task_id)
    return task is not None and task.created_by == DEMO_CREATOR


async def finish_decisions(db: AsyncSession, task_id: int, status: str) -> bool:
    """Close obsolete demo decisions after a task-page decision.

    Real tasks keep their existing approval behaviour. Rejected/cancelled
    tasks decline their pending decisions; completed tasks approve them.
    """
    if not await is_demo_task(db, task_id):
        return False
    if status in ("completed", "rejected", "cancelled"):
        await _close_decisions(
            db, task_id, "approved" if status == "completed" else "rejected"
        )
        await db.commit()
    return True


async def _close_decisions(db: AsyncSession, task_id: int, decision: str) -> None:
    from sqlalchemy import update

    from app.db.models import PendingApproval

    await db.execute(
        update(PendingApproval)
        .where(PendingApproval.task_id == task_id)
        .where(PendingApproval.status == "pending")
        .values(status=decision, decided_by="user", decided_at=func_now())
    )


async def _move(
    db: AsyncSession,
    task_id: int,
    status: str,
    message: str,
    sources: tuple[str, ...],
    **fields: Any,
) -> None:
    from sqlalchemy import update

    from app.db.models import DevTask
    from app.db.repository import append_log

    # A Fleet decision can already be queued when another page completes
    # or rejects the task. Match the lifecycle stage in the UPDATE itself,
    # so a late dispatch cannot resurrect the task or overwrite that choice.
    values = {"status": status, **fields}
    if status != "blocked":
        values["blocked_reason"] = None
    moved = await db.execute(
        update(DevTask)
        .where(DevTask.id == task_id, DevTask.created_by == DEMO_CREATOR)
        .where(DevTask.status.in_(sources))
        .values(**values)
        .returning(DevTask.id)
    )
    if moved.scalar_one_or_none() is None:
        return
    decision = _DECISION.get(message)
    if message in ("Planning started", "Restarted"):
        decision = "rejected"  # decisions from the old attempt are obsolete
    if decision is not None:
        # keep Fleet & Approvals consistent when the step was taken from the
        # task page: the task's waiting decisions are now decided
        await _close_decisions(db, task_id, decision)
    await db.commit()
    await append_log(db, task_id, "pipeline", f"{message} ({_NOTE})")


async def simulate(db: AsyncSession, task_id: int, event: str) -> bool:
    """Apply one lifecycle step to a demo task. Returns False (and does
    nothing) when the task is not demo data, so callers fall through to the
    real behaviour. An obsolete demo decision is handled as a no-op, so it
    never falls through to an AI dispatcher or changes a later stage."""
    if not await is_demo_task(db, task_id):
        return False
    sources = _EVENT_SOURCES.get(event, ())
    if event == "restart":
        from app.db.models import DevTask

        task = await db.get(DevTask, task_id)
        sources = (task.status,) if task is not None else ()
    if event == "start":
        await _move(db, task_id, "planning", "Planning started", sources)
    elif event == "plan_approved":
        await _move(db, task_id, "coding", "Plan approved; coding started", sources)
    elif event == "plan_rejected":
        await _move(db, task_id, "rejected", "Plan rejected", sources)
    elif event == "push_approved":
        await _move(
            db,
            task_id,
            "completed",
            "Changes approved and sent to GitHub",
            sources,
            pr_status="pushed",
        )
    elif event == "push_rejected":
        await _move(db, task_id, "rejected", "Sending to GitHub was declined", sources)
    elif event == "answered":
        await _move(db, task_id, "coding", "Question answered; work continues", sources)
    elif event == "declined":
        await _move(db, task_id, "blocked", "Question left unanswered", sources)
    elif event == "restart":
        await _move(db, task_id, "planning", "Restarted", sources)
    else:
        return False
    return True
