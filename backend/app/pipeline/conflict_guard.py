"""File-conflict guard — prevents two active epics from editing the same file.

Called before dispatching a coder/backend-dev/frontend-dev subtask.
Reads impacted_files from pipeline_state.architect_plan for all running epics
and returns an error string if there is overlap with the candidate file set.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Epic, PipelineState

logger = logging.getLogger(__name__)


async def check_file_conflicts(
    candidate_files: list[str],
    current_epic_id: str,
    db: AsyncSession,
) -> str | None:
    """Return conflict description if any candidate file is locked by another running epic.

    Returns None when there are no conflicts (safe to proceed).
    """
    if not candidate_files:
        return None

    candidate_set = set(candidate_files)

    # Fetch all epics in a running state (not pending/completed/failed/halted)
    running_statuses = {"planning", "coding", "testing", "ready_for_review"}
    result = await db.execute(
        select(Epic).where(
            Epic.status.in_(running_statuses),
            Epic.epic_id != current_epic_id,
        )
    )
    active_epics = result.scalars().all()

    for epic in active_epics:
        locked = await _get_epic_files(epic.epic_id, db)
        overlap = candidate_set & locked
        if overlap:
            return (
                f"File conflict: epic {epic.epic_id} ({epic.title!r}) is already "
                f"editing {sorted(overlap)}"
            )

    return None


async def _get_epic_files(epic_id: str, db: AsyncSession) -> set[str]:
    """Extract impacted_files from every PipelineState.architect_plan for an epic."""
    # All tasks in the epic share their pipeline_state; get them via task FK
    from app.db.models import DevTask

    result = await db.execute(
        select(PipelineState)
        .join(DevTask, DevTask.id == PipelineState.task_id)
        .where(DevTask.epic_id == epic_id)
    )
    states = result.scalars().all()

    files: set[str] = set()
    for ps in states:
        plan: Any = ps.architect_plan
        if isinstance(plan, dict):
            for f in plan.get("impacted_files", []):
                if isinstance(f, str):
                    files.add(f)
    return files
