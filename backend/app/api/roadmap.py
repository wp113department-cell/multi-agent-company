"""Roadmap API — T2-B10 (2026-09-24, GRIDIRON_PARTIAL #498/#484 "Roadmap
tracked, sequenced, and re-sequenced against real progress" / "Product
Management (roadmap/strategy)").

GET /api/roadmap                      — the latest tracked roadmap for a repo
PATCH /api/roadmap/items/{id}/status  — the real progress-tracking mechanism:
                                         a human (or a future automated
                                         check) marks an initiative's real
                                         status, which the NEXT
                                         roadmap_agent run for that repo
                                         reads back (see
                                         app/agents/roadmap_agent.py::
                                         _fetch_latest_roadmap_context_sync)
                                         to genuinely re-sequence around.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.repository import get_latest_roadmap_for_repo, update_roadmap_item_status
from app.middleware.rbac import require_approver, require_authenticated

router = APIRouter(prefix="/api/roadmap", tags=["roadmap"])


def _item_to_dict(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "phase": item.phase,
        "initiative": item.initiative,
        "impact": item.impact,
        "effort": item.effort,
        "confidence": item.confidence,
        "dependencies": list(item.dependencies or []),
        "sequenceOrder": item.sequence_order,
        "status": item.status,
        "updatedAt": item.updated_at.isoformat() if item.updated_at else None,
    }


@router.get("")
async def get_roadmap(
    repo_id: int | None = Query(None),
    task_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    if repo_id is None and task_id is None:
        raise HTTPException(status_code=422, detail="repo_id or task_id is required")
    roadmap = await get_latest_roadmap_for_repo(db, repo_id, task_id)
    if roadmap is None:
        return {"roadmap": None}
    return {
        "roadmap": {
            "id": roadmap.id,
            "repoId": roadmap.repo_id,
            "taskId": roadmap.task_id,
            "summary": roadmap.summary,
            "createdAt": roadmap.created_at.isoformat() if roadmap.created_at else None,
            "items": [_item_to_dict(i) for i in roadmap.items],
        }
    }


class UpdateRoadmapItemStatusRequest(BaseModel):
    status: str


@router.patch("/items/{item_id}/status")
async def patch_roadmap_item_status(
    item_id: int,
    body: UpdateRoadmapItemStatusRequest,
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_approver),
) -> dict[str, Any]:
    ok = await update_roadmap_item_status(db, item_id, body.status)
    if not ok:
        raise HTTPException(
            status_code=422,
            detail="Unknown roadmap item id or invalid status "
            "(must be planned|in_progress|completed|superseded)",
        )
    return {"ok": True, "id": item_id, "status": body.status}
