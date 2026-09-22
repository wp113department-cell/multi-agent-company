"""Agent Ratings API — T2-B3 (2026-09-22, GRIDIRON_PARTIAL #439 "User
satisfaction (real, not proxy)").

POST /api/ratings   — record a real thumbs-up/down on one agent's completed
                       work (task or chat session), replacing the audit's
                       own honestly-labeled proxy signal for this specific
                       purpose (app/agents/user_sentiment.py's regex-based
                       frustration detector stays in place for its separate,
                       real-time in-conversation purpose).

require_authenticated, not require_approver: rating past work is feedback,
not an operation on the platform (no LLM spend, no repo/task mutation) —
this is the deliberate exception the same reasoning already carved out for
/api/console/workspace/browse and the auth routes (see
tests/test_b7_auth_and_agent_authorization.py's own reviewed allowlist,
updated alongside this endpoint). A viewer giving feedback is exactly the
engagement this feature exists to capture, not something to lock behind
approver rights.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.repository import create_agent_rating
from app.middleware.rbac import require_authenticated

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ratings", tags=["ratings"])


class RateAgentRequest(BaseModel):
    agent_name: str
    rating: int = Field(..., description="+1 for thumbs-up, -1 for thumbs-down")
    task_id: str | None = None
    comment: str | None = None


@router.post("")
async def rate_agent(
    payload: RateAgentRequest,
    db: AsyncSession = Depends(get_db),
    actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    try:
        row = await create_agent_rating(
            db,
            agent_name=payload.agent_name,
            rating=payload.rating,
            task_id=payload.task_id,
            comment=payload.comment,
            rated_by=actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "Rating recorded: agent=%s rating=%+d task_id=%s by=%s",
        payload.agent_name,
        payload.rating,
        payload.task_id,
        actor,
    )
    return {
        "ok": True,
        "id": row.id,
        "agent_name": row.agent_name,
        "rating": row.rating,
    }
