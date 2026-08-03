"""Stage 2 Day 40 — app/memory/store.py's real reuse_count/importance/
verified/last_accessed_at wiring (answers.md Q120 "Memory Prioritization",
named there as "the single largest concrete gap in the whole audit").
Mirrors test_memory_archived_filter.py's real-DB-with-mocked-embedding
convention, including its content-derived fake-vector helper (needed so
distinct test rows don't collide under Day 42's dedup guard, and so every
row's description text includes the run's own uuid suffix — a literal
constant like "d"/"s" reused verbatim across multiple test functions would
otherwise hash to the exact same vector and dedup-collide across tests).
"""

from __future__ import annotations

import hashlib
import random
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.models import MemoryEmbedding
from app.memory.store import (
    _default_importance,
    _default_verified,
    embed_failure,
    embed_task_outcome,
    query_similar_tasks,
    record_memory_access,
)


def _vector_for(text_to_embed: str) -> list[float]:
    """Deterministic, content-derived fake embedding — see
    test_memory_archived_filter.py's identical helper for the full
    rationale. Uses signed [-1, 1) components, not [0, 1) — uniform
    non-negative components share a "positive orthant" bias that gives ANY
    two such vectors ~0.75-0.9 cosine similarity regardless of content
    (confirmed empirically), false-triggering the dedup guard; signed
    components give the near-zero similarity real distinct content should
    have."""
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def test_default_importance_ranks_failure_highest_then_architecture_then_learning() -> (
    None
):
    assert _default_importance("failure", "failure") == 0.8
    assert _default_importance("architecture", "architecture") == 0.7
    assert _default_importance("learning", "learning") == 0.6
    assert _default_importance("task", "completed") == 0.5
    assert _default_importance("procedure", "procedure") == 0.5


def test_default_verified_true_only_for_completed_outcome() -> None:
    assert _default_verified("completed") is True
    assert _default_verified("blocked") is False
    assert _default_verified("failure") is False
    assert _default_verified("architecture") is False


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_task_outcome_completed_is_verified_with_real_default_importance(
    _mock_embed: object,
) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-gap40-verified-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_task_outcome(
                task_id=task_id,
                description=f"gap40 verified-default marker {suffix}",
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert row is not None
            assert row.verified is True
            assert row.importance == 0.5
            assert row.reuse_count == 0
            assert row.last_accessed_at is None

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_failure_is_not_verified_and_has_higher_default_importance(
    _mock_embed: object,
) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-gap40-failure-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_failure(
                task_id=task_id,
                error_description=f"boom {suffix}",
                root_cause="root",
                db=session,
            )
            assert row is not None
            assert row.verified is False
            assert row.importance == 0.8

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_record_memory_access_increments_reuse_count_and_stamps_last_accessed(
    _mock_embed: object,
) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-gap40-access-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_task_outcome(
                task_id=task_id,
                description=f"gap40 record-access marker {suffix}",
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert row is not None
            memory_id = row.id

            await record_memory_access([memory_id], session)
            refetched = (
                await session.execute(
                    select(MemoryEmbedding).where(MemoryEmbedding.id == memory_id)
                )
            ).scalar_one()
            assert refetched.reuse_count == 1
            assert refetched.last_accessed_at is not None

            # A second access accumulates rather than resetting.
            await record_memory_access([memory_id], session)
            refetched_again = (
                await session.execute(
                    select(MemoryEmbedding).where(MemoryEmbedding.id == memory_id)
                )
            ).scalar_one()
            assert refetched_again.reuse_count == 2

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_record_memory_access_empty_list_is_a_safe_noop() -> None:
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await record_memory_access([], session)  # must not raise
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_query_similar_tasks_includes_id_and_increments_reuse_count(
    _mock_embed: object,
) -> None:
    """End-to-end proof that a real query_* call both returns the row's id
    (needed by any caller wanting to later act on reuse) and actually
    increments reuse_count for every row it returns — not just that the
    helper function works in isolation."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-gap40-query-reuse-{suffix}"
    marker = f"unique marker for reuse-count test {suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            written = await embed_task_outcome(
                task_id=task_id,
                description=marker,
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert written is not None
            assert written.reuse_count == 0

            results = await query_similar_tasks(marker, session, top_k=1000)
            matching = [r for r in results if r["task_id"] == task_id]
            assert len(matching) == 1
            assert matching[0]["id"] == written.id

            refetched = (
                await session.execute(
                    select(MemoryEmbedding).where(MemoryEmbedding.id == written.id)
                )
            ).scalar_one()
            assert refetched.reuse_count == 1
            assert refetched.last_accessed_at is not None

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await session.commit()
    finally:
        await engine.dispose()
