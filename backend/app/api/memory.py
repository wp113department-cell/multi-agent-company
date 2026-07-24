"""Engineering Memory API — GET /api/memory/patterns (read-only)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db.models import MemoryEmbedding, VersionedLesson
from app.memory.store import query_similar_tasks
from app.middleware.rbac import require_approver

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])


_VALID_CATEGORIES = {"task", "architecture", "failure", "learning"}


@router.get("/patterns")
async def get_memory_patterns(
    db: AsyncSession = Depends(get_db),
    category: str | None = Query(
        default=None,
        description="Filter by category: task | architecture | failure | learning",
    ),
) -> dict[str, Any]:
    """Aggregate view of engineering memory: outcome distribution and recent embeddings.

    Optional ?category= filter returns only memories of that category.
    """
    base_q = select(MemoryEmbedding)
    count_q = select(func.count(MemoryEmbedding.id))
    dist_q = select(
        MemoryEmbedding.outcome, func.count(MemoryEmbedding.id).label("count")
    ).group_by(MemoryEmbedding.outcome)

    if category and category in _VALID_CATEGORIES:
        base_q = base_q.where(MemoryEmbedding.category == category)
        count_q = count_q.where(MemoryEmbedding.category == category)
        dist_q = dist_q.where(MemoryEmbedding.category == category)

    result = await db.execute(dist_q)
    distribution = {row.outcome: row.count for row in result.fetchall()}

    count_result = await db.execute(count_q)
    total = count_result.scalar_one_or_none() or 0

    recent_result = await db.execute(
        base_q.order_by(MemoryEmbedding.created_at.desc()).limit(10)
    )
    recent = recent_result.scalars().all()

    # Category distribution (all categories always shown)
    cat_dist_result = await db.execute(
        select(
            MemoryEmbedding.category, func.count(MemoryEmbedding.id).label("count")
        ).group_by(MemoryEmbedding.category)
    )
    category_distribution = {
        row.category: row.count for row in cat_dist_result.fetchall()
    }

    return {
        "total": total,
        "category": category,
        "categoryDistribution": category_distribution,
        "outcomeDistribution": distribution,
        "recent": [
            {
                "id": r.id,
                "taskId": r.task_id,
                "epicId": r.epic_id,
                "outcome": r.outcome,
                "category": getattr(r, "category", "task"),
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


@router.get("/lessons")
async def list_versioned_lessons(
    state: str | None = Query(
        default=None,
        description="Filter by lifecycle state: draft | published | superseded | merged_into | archived",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List versioned lessons (Day 11 durable lesson lifecycle).

    Audit 03 gap-closure (2026-07-24) — added alongside the rollback endpoint
    below so rollback() has a real, reachable way to discover a lesson_id
    rather than being unreachable infrastructure.
    """
    q = select(VersionedLesson)
    if state:
        q = q.where(VersionedLesson.state == state)
    q = q.order_by(VersionedLesson.created_at.desc()).limit(limit)
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "lessonId": r.lesson_id,
            "topic": r.topic,
            "content": r.content,
            "version": r.version,
            "state": r.state,
            "supersedesId": r.supersedes_id,
            "createdAt": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/lessons/{lesson_id}/rollback")
async def rollback_versioned_lesson(
    lesson_id: str,
    user_id: str = Depends(require_approver),
) -> dict[str, Any]:
    """Roll back a versioned lesson to its most recently superseded version.

    Audit 03 gap-closure (2026-07-24) — VersionedMemoryStore.rollback() was
    fully built and tested since Day 11 but had zero real callers anywhere.
    This is its first real trigger.

    VersionedMemoryStore.rollback() is a sync method that calls asyncio.run()
    internally (see app/fleet/versioned_memory.py's own documented reasoning
    for why a fresh, isolated engine is used there) — this route handler
    already has a running event loop, so the call is dispatched via
    asyncio.to_thread(), the same safe pattern main.py's archive loop uses
    for the sibling archive_expired() call.
    """
    from app.fleet.versioned_memory import get_versioned_memory_store

    try:
        record = await asyncio.to_thread(
            get_versioned_memory_store().rollback, lesson_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    logger.info(
        "Versioned lesson %s rolled back to version %d by %s",
        lesson_id,
        record.version,
        user_id,
    )
    return {
        "lessonId": record.lesson_id,
        "topic": record.topic,
        "content": record.content,
        "version": record.version,
        "state": record.state,
        "rolledBackBy": user_id,
    }
