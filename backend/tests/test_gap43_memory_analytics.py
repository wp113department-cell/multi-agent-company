"""Stage 2 Day 43 — app/memory/analytics.py (answers.md Q120 "Memory
Analytics": total memory size, average retrieval time, memory growth,
duplicate memories, and unused memories were all NO/PARTIAL with zero
instrumentation before this day). Real-DB tests throughout, per this
session's established convention — signed content-derived fake vectors
(see test_memory_archived_filter.py's identical helper) where a similarity
comparison is involved.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.api.memory import get_memory_analytics
from app.config import get_settings, reset_settings_cache
from app.db.models import MemoryEmbedding
from app.memory.analytics import (
    compute_memory_analytics,
    get_retrieval_time_stats,
    record_retrieval_time,
    reset_retrieval_time_stats,
)
from app.memory.store import embed_task_outcome


def _vector_for(text_to_embed: str) -> list[float]:
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def test_record_and_get_retrieval_time_stats() -> None:
    reset_retrieval_time_stats()
    try:
        record_retrieval_time("query_similar_tasks", 10.0)
        record_retrieval_time("query_similar_tasks", 20.0)
        record_retrieval_time("query_failures", 5.0)

        stats = get_retrieval_time_stats()
        assert stats["query_similar_tasks"]["count"] == 2
        assert stats["query_similar_tasks"]["avg_ms"] == 15.0
        assert stats["query_similar_tasks"]["min_ms"] == 10.0
        assert stats["query_similar_tasks"]["max_ms"] == 20.0
        assert stats["query_failures"]["count"] == 1
    finally:
        reset_retrieval_time_stats()


def test_retrieval_time_window_respects_configured_max_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORY_RETRIEVAL_TIME_WINDOW", "3")
    reset_settings_cache()
    reset_retrieval_time_stats()
    try:
        for i in range(10):
            record_retrieval_time("query_procedures", float(i))
        stats = get_retrieval_time_stats()
        # Only the most recent 3 samples (7, 8, 9) survive.
        assert stats["query_procedures"]["count"] == 3
        assert stats["query_procedures"]["avg_ms"] == 8.0
    finally:
        reset_retrieval_time_stats()
        reset_settings_cache()


def test_reset_retrieval_time_stats_clears_all() -> None:
    record_retrieval_time("query_similar_tasks", 1.0)
    reset_retrieval_time_stats()
    assert get_retrieval_time_stats() == {}


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_compute_memory_analytics_real_counts(_mock_embed: object) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_fresh = f"td-gap43-fresh-{suffix}"
    task_unused = f"td-gap43-unused-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            fresh = await embed_task_outcome(
                task_id=task_fresh,
                description=f"gap43 fresh marker {suffix}",
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            unused = await embed_task_outcome(
                task_id=task_unused,
                description=f"gap43 unused marker {suffix}",
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert fresh is not None and unused is not None

            settings = get_settings()
            # Backdate the "unused" row past the unused-threshold, with
            # reuse_count left at its real default (0) — this row must be
            # counted; the fresh row (reuse_count=0 but not old) must not.
            age_days = settings.memory_unused_threshold_days + 5
            await session.execute(
                text(
                    "UPDATE memory_embeddings SET created_at = now() - "
                    "(CAST(:age_days AS double precision) * interval '1 day') "
                    "WHERE id = :id"
                ),
                {"age_days": age_days, "id": unused.id},
            )
            await session.commit()

            analytics = await compute_memory_analytics(session)

            assert analytics.total_rows >= 2
            assert analytics.total_size_bytes > 0
            # The fresh row was created today — real trend, not a snapshot.
            assert any(
                day["day"] for day in analytics.growth_by_day
            ), "expected at least one real growth-by-day bucket"
            assert analytics.unused_count >= 1

            await session.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id.in_([task_fresh, task_unused])
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_pairs_count_detects_real_near_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dedup (Day 42) prevents *future* duplicate writes; this analytic
    must still be able to see duplicates already in the table (e.g.
    written before Day 42, or with dedup off) — so this test disables
    dedup to construct that exact scenario."""
    monkeypatch.setenv("MEMORY_DEDUP_ENABLED", "false")
    reset_settings_cache()
    try:
        engine = _engine()
        suffix = uuid.uuid4().hex[:8]
        task_a = f"td-gap43-dup-a-{suffix}"
        task_b = f"td-gap43-dup-b-{suffix}"
        marker = f"gap43 duplicate-pair marker {suffix}"
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                with patch("app.memory.store._embed", side_effect=_vector_for):
                    row_a = await embed_task_outcome(
                        task_id=task_a,
                        description=marker,
                        summary="s",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                    )
                    row_b = await embed_task_outcome(
                        task_id=task_b,
                        description=marker,
                        summary="s",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                    )
                assert row_a is not None and row_b is not None
                assert row_a.id != row_b.id  # dedup genuinely off

                analytics = await compute_memory_analytics(session)
                assert analytics.duplicate_pairs_count is not None
                assert analytics.duplicate_pairs_count >= 1

                await session.execute(
                    delete(MemoryEmbedding).where(
                        MemoryEmbedding.task_id.in_([task_a, task_b])
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()
    finally:
        reset_settings_cache()


@pytest.mark.asyncio
async def test_duplicate_scan_skipped_when_table_exceeds_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Config-driven, not hardcoded: memory_dup_scan_max_rows=0 must skip
    the O(n^2) scan with a real, honest reason string — never silently
    eat an unbounded cost."""
    monkeypatch.setenv("MEMORY_DUP_SCAN_MAX_ROWS", "0")
    reset_settings_cache()
    try:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                analytics = await compute_memory_analytics(session)
                assert analytics.duplicate_pairs_count is None
                assert analytics.duplicate_scan_skipped_reason is not None
                assert (
                    "memory_dup_scan_max_rows"
                    in analytics.duplicate_scan_skipped_reason
                )
        finally:
            await engine.dispose()
    finally:
        reset_settings_cache()


@pytest.mark.asyncio
async def test_get_memory_analytics_endpoint_real_db() -> None:
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            result = await get_memory_analytics(db=session)
            assert "totalRows" in result
            assert "totalSizeBytes" in result
            assert "growthByDay" in result
            assert "unusedCount" in result
            assert "duplicatePairsCount" in result
            assert "duplicateScanSkippedReason" in result
            assert "retrievalTimeStats" in result
            assert isinstance(result["totalRows"], int)
            assert isinstance(result["totalSizeBytes"], int)
    finally:
        await engine.dispose()
