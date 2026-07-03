"""Engineering Memory API — GET /api/memory/patterns (read-only)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import MemoryEmbedding
from app.memory.store import query_similar_tasks

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/patterns")
async def get_memory_patterns(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Aggregate view of engineering memory: outcome distribution and recent embeddings."""
    result = await db.execute(
        select(MemoryEmbedding.outcome, func.count(MemoryEmbedding.id).label("count"))
        .group_by(MemoryEmbedding.outcome)
    )
    distribution = {row.outcome: row.count for row in result.fetchall()}

    count_result = await db.execute(select(func.count(MemoryEmbedding.id)))
    total = count_result.scalar_one_or_none() or 0

    # Recent entries
    recent_result = await db.execute(
        select(MemoryEmbedding)
        .order_by(MemoryEmbedding.created_at.desc())
        .limit(10)
    )
    recent = recent_result.scalars().all()

    return {
        "total": total,
        "outcomeDistribution": distribution,
        "recent": [
            {
                "id": r.id,
                "taskId": r.task_id,
                "epicId": r.epic_id,
                "outcome": r.outcome,
                "description": r.description[:200],
                "summary": r.summary[:200],
                "filesChanged": list(r.files_changed or [])[:10],
                "createdAt": r.created_at.isoformat(),
            }
            for r in recent
        ],
    }


@router.get("/search")
async def search_memory(
    q: str = Query(..., description="Task description to find similar past tasks"),
    top_k: int = Query(default=3, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Search engineering memory for similar past tasks by description."""
    results = await query_similar_tasks(description=q, db=db, top_k=top_k)
    return results
