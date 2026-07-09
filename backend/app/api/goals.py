"""Goals API — POST /api/goals, GET /api/goals, GET /api/goals/{goal_id}."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.executive import run_executive
from app.db.models import Goal
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/goals", tags=["goals"])


class CreateGoalRequest(BaseModel):
    text: str


class GoalResponse(BaseModel):
    goal_id: str
    text: str
    status: str
    epic_ids: list[str]
    summary: str | None

    model_config = {"from_attributes": True}


@router.post("", status_code=status.HTTP_201_CREATED, response_model=GoalResponse)
async def create_goal(
    body: CreateGoalRequest,
    db: AsyncSession = Depends(get_db),
) -> Any:
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="goal text cannot be empty")

    goal_id, epic_ids, error = await run_executive(body.text.strip(), db)
    if error:
        raise HTTPException(status_code=500, detail=f"Executive agent error: {error}")

    await db.commit()

    row = await db.get(Goal, goal_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Goal not found after creation")
    return row


@router.get("", response_model=list[GoalResponse])
async def list_goals(
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(select(Goal).order_by(Goal.created_at.desc()))
    return result.scalars().all()


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(
    goal_id: str,
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await db.get(Goal, goal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return row
