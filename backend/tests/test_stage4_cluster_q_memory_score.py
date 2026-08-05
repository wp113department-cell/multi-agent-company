"""Stage 4 Cluster Q — Memory category (2026-08-05, STAGE4_BACKLOG.md).

Verified before writing this module that app/memory/store.py's per-row
retrieval-ranking formula (colloquially "memory_score" in the original
finding) is the wrong kind of signal for a subsystem-health score — it
ranks candidate memories per query, it doesn't measure the health of a
repo's memory pool over time. The real, structured, already-persisted
signal used instead is `memory_embeddings.verified` (a real boolean, set
at write time by app/memory/store.py::_default_verified() — True only
when outcome == "completed", never invented). This category computes
verified_ratio: the fraction of a repo's real (non-archived) memory rows
that are verified.

Real end-to-end path proven here, matching the same discipline as
Tests/Architecture/Security: memories are seeded through the REAL
embed_task_outcome()/embed_failure() write path (never hand-inserted via
raw SQL), get_latest_memory_score() reads them back live, and a follow-up
write is proven to change the aggregate — since this category has no
discrete "review run" the way the other 3 do (memory_embeddings is a
continuously-accumulating pool), there is no separate persistence step to
test; the read IS the live aggregation over already-durably-persisted
facts, and that live-ness is exactly what test_adding_a_memory_changes_
the_score_live proves.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import MemoryEmbedding, Repo
from app.db.session import new_isolated_async_engine
from app.fleet.memory_score import compute_memory_score, get_latest_memory_score
from app.memory.store import embed_failure, embed_task_outcome


def _vector_for(text_to_embed: str) -> list[float]:
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


# ---------------------------------------------------------------------------
# compute_memory_score() — pure function, no DB
# ---------------------------------------------------------------------------


def test_zero_total_count_returns_none_not_a_fabricated_score() -> None:
    """Absence of memory rows is absence of data, not evidence of health —
    must never be reported as a score at all (unlike a clean architecture
    review, which is itself a real positive signal)."""
    assert compute_memory_score(0, 0) is None


def test_ratio_computed_correctly() -> None:
    result = compute_memory_score(total_count=4, verified_count=3)
    assert result is not None
    assert result.memory_score == 0.75
    assert result.total_count == 4
    assert result.verified_count == 3


def test_all_verified_scores_1() -> None:
    result = compute_memory_score(total_count=5, verified_count=5)
    assert result is not None
    assert result.memory_score == 1.0


def test_none_verified_scores_0() -> None:
    result = compute_memory_score(total_count=5, verified_count=0)
    assert result is not None
    assert result.memory_score == 0.0


# ---------------------------------------------------------------------------
# Real-Postgres end-to-end: seeded via the REAL memory write path
# ---------------------------------------------------------------------------


def _make_repo_sync(suffix: str) -> int:
    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                repo = Repo(
                    github_url=f"https://github.com/test/clusterq-mem-{suffix}",
                    name=f"clusterq-mem-{suffix}",
                    local_path=f"/tmp/clusterq-mem-{suffix}",
                    status="ready",
                )
                session.add(repo)
                await session.commit()
                await session.refresh(repo)
                return int(repo.id)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _seed_completed_outcome_sync(task_id: str, repo_id: int, marker: str) -> None:
    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                with patch("app.memory.store._embed", side_effect=_vector_for):
                    await embed_task_outcome(
                        task_id=task_id,
                        # Distinct text per call — embed_task_outcome runs real
                        # near-duplicate detection (app/memory/store.py's
                        # _find_near_duplicate); identical description/summary
                        # text across calls yields identical mocked vectors and
                        # legitimately merges into one row, which would silently
                        # undercount total_count here if every seed used the
                        # same text.
                        description=f"did the thing {marker}",
                        summary=f"done {marker}",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                        repo_id=repo_id,
                    )
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _seed_failure_sync(task_id: str, repo_id: int, marker: str) -> None:
    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                with patch("app.memory.store._embed", side_effect=_vector_for):
                    await embed_failure(
                        task_id=task_id,
                        error_description=f"it broke {marker}",
                        root_cause=f"bad input {marker}",
                        db=session,
                        repo_id=repo_id,
                    )
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _cleanup_sync(task_ids: list[str], repo_ids: list[int]) -> None:
    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(MemoryEmbedding).where(MemoryEmbedding.task_id.in_(task_ids))
                )
                await session.execute(delete(Repo).where(Repo.id.in_(repo_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_no_memory_rows_for_repo_returns_none() -> None:
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)

    try:
        assert get_latest_memory_score(repo_id) is None
    finally:
        _cleanup_sync([], [repo_id])


def test_real_write_path_verified_ratio_computed_correctly() -> None:
    """Seeds via the real embed_task_outcome()/embed_failure() functions —
    never raw SQL — proving the score reflects real memory-write outcomes,
    not a synthetic fixture shape."""
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_a = f"mem-a-{suffix}"
    task_b = f"mem-b-{suffix}"
    task_c = f"mem-c-{suffix}"

    try:
        _seed_completed_outcome_sync(task_a, repo_id, "a")  # verified=True
        _seed_completed_outcome_sync(task_b, repo_id, "b")  # verified=True
        _seed_failure_sync(task_c, repo_id, "c")  # verified=False

        result = get_latest_memory_score(repo_id)
        assert result is not None
        assert result.total_count == 3
        assert result.verified_count == 2
        assert result.memory_score == pytest.approx(2 / 3, abs=1e-6)
    finally:
        _cleanup_sync([task_a, task_b, task_c], [repo_id])


def test_adding_a_memory_changes_the_score_live() -> None:
    """The literal 'reflected correctly' proof for this category: since
    Memory has no discrete review-run snapshot, this proves the read
    itself is live — a new write immediately changes what
    get_latest_memory_score() returns, with no caching/staleness."""
    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_a = f"mem-live-a-{suffix}"
    task_b = f"mem-live-b-{suffix}"

    try:
        _seed_completed_outcome_sync(task_a, repo_id, "a")
        first = get_latest_memory_score(repo_id)
        assert first is not None
        assert first.memory_score == 1.0
        assert first.total_count == 1

        _seed_failure_sync(task_b, repo_id, "b")
        second = get_latest_memory_score(repo_id)
        assert second is not None
        assert second.memory_score == 0.5, (
            "get_latest_memory_score() must reflect the newly written "
            "memory row immediately — not a stale earlier read"
        )
        assert second.total_count == 2
    finally:
        _cleanup_sync([task_a, task_b], [repo_id])


# ---------------------------------------------------------------------------
# Aggregator integration — proves Memory shows up correctly in
# app.fleet.quality_score.get_quality_score(), not just in isolation.
# ---------------------------------------------------------------------------


def test_memory_appears_available_in_the_aggregate_with_real_data() -> None:
    from app.fleet.quality_score import get_quality_score

    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_a = f"mem-agg-a-{suffix}"

    try:
        _seed_completed_outcome_sync(task_a, repo_id, "a")

        result = get_quality_score(repo_id)
        by_name = {c.name: c for c in result.categories}

        assert by_name["memory"].status == "available"
        assert by_name["memory"].score == 1.0
        assert result.overall_score == 1.0
        assert result.available_category_count == 1
    finally:
        _cleanup_sync([task_a], [repo_id])


def test_changing_memory_data_changes_the_aggregate_overall_score() -> None:
    """The literal 'reflected correctly in the aggregated result' proof at
    the aggregator level (not just get_latest_memory_score() directly)."""
    from app.fleet.quality_score import get_quality_score

    suffix = uuid.uuid4().hex[:8]
    repo_id = _make_repo_sync(suffix)
    task_a = f"mem-agg-live-a-{suffix}"
    task_b = f"mem-agg-live-b-{suffix}"

    try:
        _seed_completed_outcome_sync(task_a, repo_id, "a")
        first = get_quality_score(repo_id)
        assert first.overall_score == 1.0

        _seed_failure_sync(task_b, repo_id, "b")
        second = get_quality_score(repo_id)
        assert second.overall_score == 0.5, (
            "get_quality_score() must reflect the new memory write in its "
            "overall_score, not a stale earlier aggregate"
        )
    finally:
        _cleanup_sync([task_a, task_b], [repo_id])
