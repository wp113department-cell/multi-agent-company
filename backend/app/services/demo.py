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


def func_now() -> Any:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


async def is_demo_task(db: AsyncSession, task_id: int | None) -> bool:
    if task_id is None:
        return False
    from app.db.models import DevTask

    task = await db.get(DevTask, task_id)
    return task is not None and task.created_by == DEMO_CREATOR


async def _move(
    db: AsyncSession,
    task_id: int,
    status: str,
    message: str,
    **fields: Any,
) -> None:
    from app.db.models import DevTask
    from app.db.repository import append_log

    task = await db.get(DevTask, task_id)
    if task is None:
        return
    decision = _DECISION.get(message)
    if decision is not None:
        # keep Fleet & Approvals consistent when the step was taken from the
        # task page: the task's waiting decisions are now decided
        from sqlalchemy import update

        from app.db.models import PendingApproval

        await db.execute(
            update(PendingApproval)
            .where(PendingApproval.task_id == task_id)
            .where(PendingApproval.status == "pending")
            .values(status=decision, decided_by="user", decided_at=func_now())
        )
    task.status = status
    for k, v in fields.items():
        setattr(task, k, v)
    await db.commit()
    await append_log(db, task_id, "pipeline", f"{message} ({_NOTE})")


async def simulate(db: AsyncSession, task_id: int, event: str) -> bool:
    """Apply one lifecycle step to a demo task. Returns False (and does
    nothing) when the task is not demo data, so callers fall through to the
    real behaviour."""
    if not await is_demo_task(db, task_id):
        return False
    if event == "start":
        await _move(db, task_id, "planning", "Planning started")
    elif event == "plan_approved":
        await _move(db, task_id, "coding", "Plan approved; coding started")
    elif event == "plan_rejected":
        await _move(db, task_id, "rejected", "Plan rejected")
    elif event == "push_approved":
        await _move(
            db,
            task_id,
            "completed",
            "Changes approved and sent to GitHub",
            pr_status="pushed",
        )
    elif event == "push_rejected":
        await _move(db, task_id, "rejected", "Sending to GitHub was declined")
    elif event == "answered":
        await _move(db, task_id, "coding", "Question answered; work continues")
    elif event == "declined":
        await _move(db, task_id, "blocked", "Question left unanswered")
    elif event == "restart":
        await _move(db, task_id, "planning", "Restarted")
    else:
        return False
    return True
