"""Goals API — POST /api/goals, GET /api/goals, GET /api/goals/{goal_id}.

G11 (2026-10-19): a goal belongs to a project. The executive agent breaks it
into epics of that project ("proposed" — nothing runs until the user starts
one with POST /api/epics/{id}/start), and the goal's status follows its
epics: proposed → in_progress → done.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.executive import run_executive
from app.api.epics import EpicId  # same UUID check: a bad id is a 422, not a 500
from app.db.models import Epic, Goal, Project
from app.db.session import get_db
from app.middleware.rbac import require_approver, require_authenticated

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/goals", tags=["goals"])

# An epic in one of these is finished; anything else that is not "proposed"
# is under way.
_EPIC_FINISHED = {"approved", "completed", "rejected"}


class CreateGoalRequest(BaseModel):
    text: str
    project_id: int | None = None


def goal_status(goal: Goal, epics: list[Epic]) -> str:
    """A broken-down goal's status comes from its epics; a goal label (no
    epics) keeps its stored status."""
    if not goal.epic_ids or not epics:
        return goal.status
    statuses = [e.status for e in epics]
    if all(s == "proposed" for s in statuses):
        return "proposed"
    if all(s in _EPIC_FINISHED for s in statuses):
        return "done"
    return "in_progress"


async def _response(db: AsyncSession, goal: Goal) -> dict[str, Any]:
    epics: list[Epic] = []
    if goal.epic_ids:
        found = {
            e.epic_id: e
            for e in (
                await db.execute(select(Epic).where(Epic.epic_id.in_(goal.epic_ids)))
            ).scalars()
        }
        epics = [found[i] for i in goal.epic_ids if i in found]
    return {
        "goalId": goal.goal_id,
        "text": goal.text,
        "status": goal_status(goal, epics),
        "summary": goal.summary,
        "projectId": goal.project_id,
        "epicIds": list(goal.epic_ids or []),
        "epics": [
            {
                "epicId": e.epic_id,
                "title": e.title,
                "description": e.description,
                "status": e.status,
            }
            for e in epics
        ],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_goal(
    body: CreateGoalRequest,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_approver),
) -> dict[str, Any]:
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="goal text cannot be empty")

    repo_id = None
    if body.project_id is not None:
        project = await db.get(Project, body.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        repo_id = project.repo_id

    goal_id, epic_ids, error = await run_executive(
        body.text.strip(), db, project_id=body.project_id, repo_id=repo_id
    )
    if error:
        raise HTTPException(status_code=500, detail=f"Executive agent error: {error}")

    await db.commit()

    row = await db.get(Goal, goal_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Goal not found after creation")
    return await _response(db, row)


@router.get("")
async def list_goals(
    project_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> list[dict[str, Any]]:
    query = select(Goal).order_by(Goal.created_at.desc())
    if project_id is not None:
        query = query.where(Goal.project_id == project_id)
    return [await _response(db, g) for g in (await db.execute(query)).scalars()]


@router.get("/{goal_id}")
async def get_goal(
    goal_id: EpicId,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    row = await db.get(Goal, goal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return await _response(db, row)
