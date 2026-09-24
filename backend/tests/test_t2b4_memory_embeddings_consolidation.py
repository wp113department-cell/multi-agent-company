"""T2-B4 (2026-09-22, GRIDIRON_PARTIAL #100 "Memory Evolution (active
shrink/consolidate over time)").

app/services/retention.py already archives old memory_embeddings rows on a
fixed age timer, but never reduces distinct-topic count while a memory is
still active — this is the real, separate consolidation capability: find
clusters of old, mutually-similar rows and merge them via a real LLM call
(mocked here, per this suite's own established convention — see
tests/test_lesson_compression.py's identical note), archiving the losers.

Real Postgres end to end for the DB-touching pieces (candidate fetch,
clustering, the actual merge/archive), matching
tests/test_gap41_composite_scoring.py's own convention.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import MemoryEmbedding
from app.memory.consolidation import (
    _CandidateRow,
    _cosine_similarity,
    consolidate_group,
    find_consolidation_groups,
)
from app.memory.store import embed_task_outcome


def _vector_for(text_to_embed: str) -> list[float]:
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _mock_anthropic_response(text: str) -> Any:
    return MagicMock(
        content=[MagicMock(type="text", text=text)],
        usage=MagicMock(input_tokens=10, output_tokens=5),
    )


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


def test_consolidation_is_off_by_default_deliberately() -> None:
    """Unlike a per-task agent run, this is unbounded automatic background
    LLM spend running forever — must be an explicit opt-in, not a surprise
    default cost."""
    settings = get_settings()
    assert settings.memory_embeddings_consolidation_enabled is False


def test_config_settings_are_distinctly_named_from_versioned_lesson_consolidation() -> (
    None
):
    """Real regression guard for the naming collision caught while building
    this: memory_consolidation_* already exists for versioned_lessons —
    this feature's settings must be memory_EMBEDDINGS_consolidation_*."""
    settings = get_settings()
    assert hasattr(settings, "memory_embeddings_consolidation_enabled")
    assert hasattr(settings, "memory_embeddings_consolidation_min_age_days")
    # The pre-existing versioned_lessons setting must be untouched/still real.
    assert settings.memory_consolidation_enabled is True


# ---------------------------------------------------------------------------
# _cosine_similarity / find_consolidation_groups — pure unit tests
# ---------------------------------------------------------------------------


def _row(id_: int, repo_id: int | None, embedding: list[float]) -> _CandidateRow:
    return _CandidateRow(
        id=id_,
        repo_id=repo_id,
        description=f"row {id_}",
        summary=f"summary {id_}",
        importance=0.5,
        reuse_count=0,
        verified=False,
        embedding=embedding,
    )


def test_cosine_similarity_identical_vectors_is_one() -> None:
    v = [1.0, 2.0, 3.0]
    assert _cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_zero_vector_is_zero_not_a_crash() -> None:
    assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_find_consolidation_groups_clusters_similar_rows_only() -> None:
    a = [1.0, 0.0, 0.0]
    b = [0.99, 0.01, 0.0]  # near-identical to a
    c = [0.0, 0.0, 1.0]  # orthogonal — unrelated
    rows = [_row(1, None, a), _row(2, None, b), _row(3, None, c)]
    groups = find_consolidation_groups(
        rows, min_group_size=2, similarity_threshold=0.9, max_groups=5
    )
    assert len(groups) == 1
    assert {r.id for r in groups[0]} == {1, 2}


def test_find_consolidation_groups_never_mixes_different_repos() -> None:
    a = [1.0, 0.0, 0.0]
    rows = [_row(1, repo_id=10, embedding=a), _row(2, repo_id=20, embedding=a)]
    groups = find_consolidation_groups(
        rows, min_group_size=2, similarity_threshold=0.9, max_groups=5
    )
    assert groups == []  # identical vectors but different repos — never grouped


def test_find_consolidation_groups_respects_max_groups_cap() -> None:
    rows = []
    for cluster in range(5):
        base = [0.0] * 5
        base[cluster] = 1.0
        rows.append(_row(cluster * 2, None, base))
        rows.append(_row(cluster * 2 + 1, None, [x + 0.001 for x in base]))
    groups = find_consolidation_groups(
        rows, min_group_size=2, similarity_threshold=0.9, max_groups=2
    )
    assert len(groups) == 2  # 5 real qualifying clusters exist, capped to 2


# ---------------------------------------------------------------------------
# consolidate_group — real Postgres, mocked LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consolidate_group_merges_and_archives_real_rows() -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_a = f"td-t2b4-consolidate-a-{suffix}"
    task_b = f"td-t2b4-consolidate-b-{suffix}"
    marker_a = f"consolidation candidate A {suffix}"
    marker_b = f"consolidation candidate B {suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            with patch("app.memory.store._embed", side_effect=_vector_for):
                row_a = await embed_task_outcome(
                    task_id=task_a,
                    description=marker_a,
                    summary="s-a",
                    outcome="completed",
                    files_changed=[],
                    db=session,
                )
                row_b = await embed_task_outcome(
                    task_id=task_b,
                    description=marker_b,
                    summary="s-b",
                    outcome="completed",
                    files_changed=[],
                    db=session,
                )
            assert row_a is not None and row_b is not None

            # Give row_b a real reuse/importance signal that must survive
            # onto the merged survivor (row_a, the "oldest" by convention —
            # callers always pass oldest-first).
            await session.execute(
                update(MemoryEmbedding)
                .where(MemoryEmbedding.id == row_b.id)
                .values(reuse_count=7, importance=0.9, verified=True)
            )
            await session.commit()

            group = [
                _row(row_a.id, row_a.repo_id, [1.0]),
                _row(row_b.id, row_b.repo_id, [1.0]),
            ]
            # importance/reuse_count/verified in the _CandidateRow objects
            # themselves are what consolidate_group actually reads for the
            # max()/any() computation — reflect the real DB values.
            group[1].reuse_count = 7
            group[1].importance = 0.9
            group[1].verified = True

            with patch("anthropic.Anthropic") as mock_cls:
                mock_client = MagicMock()
                mock_client.messages.create.return_value = _mock_anthropic_response(
                    "merged consolidated summary text"
                )
                mock_cls.return_value = mock_client

                ok = await consolidate_group(
                    session, group, "claude-haiku-4-5-20251001", 5.0
                )

            assert ok is True

            await session.refresh(row_a)
            await session.refresh(row_b)
            assert row_a.description == "merged consolidated summary text"
            assert row_a.archived is False
            assert row_a.importance == 0.9  # max(0.5, 0.9)
            assert row_a.reuse_count == 7  # max(0, 7)
            assert row_a.verified is True  # any([False, True])
            assert row_b.archived is True  # the loser, archived not deleted
            assert row_b.description == marker_b  # untouched, still real data
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id.in_([task_a, task_b])
                )
            )
            await session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_consolidate_group_leaves_rows_untouched_when_llm_call_fails() -> None:
    """A failed merge must never lose or corrupt real data — the caller's
    per-cycle loop just skips this group, exactly like LessonStore._compress_
    group's identical fail-safe contract."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-t2b4-consolidate-fail-{suffix}"
    marker = f"consolidation failure-path marker {suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            with patch("app.memory.store._embed", side_effect=_vector_for):
                row = await embed_task_outcome(
                    task_id=task_id,
                    description=marker,
                    summary="s",
                    outcome="completed",
                    files_changed=[],
                    db=session,
                )
            assert row is not None
            original_description = row.description

            group = [
                _row(row.id, row.repo_id, [1.0]),
                _row(999999999, row.repo_id, [1.0]),
            ]

            with patch("anthropic.Anthropic", side_effect=RuntimeError("network down")):
                ok = await consolidate_group(
                    session, group, "claude-haiku-4-5-20251001", 5.0
                )

            assert ok is False
            await session.refresh(row)
            assert row.description == original_description
            assert row.archived is False
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_memory_consolidation_cycle_respects_the_global_group_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real cost-control proof: even with many real qualifying clusters
    across categories, the cycle never makes more LLM calls than
    memory_embeddings_consolidation_max_groups_per_cycle."""
    from app.config import reset_settings_cache
    from app.memory.consolidation import run_memory_consolidation_cycle

    old_cutoff_marker = f"td-t2b4-cycle-{uuid.uuid4().hex[:8]}"
    task_ids = []
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            for i in range(6):  # 3 clusters of 2 each — real similar pairs
                cluster = i // 2
                task_id = f"{old_cutoff_marker}-{i}"
                task_ids.append(task_id)
                marker = f"cycle cluster {cluster} member {i} {old_cutoff_marker}"
                fake_vec = [0.0] * 1536
                fake_vec[cluster] = 1.0
                with patch("app.memory.store._embed", return_value=fake_vec), patch(
                    "app.memory.store._find_near_duplicate", return_value=None
                ):
                    await embed_task_outcome(
                        task_id=task_id,
                        description=marker,
                        summary="s",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                    )
            # Backdate all 6 rows past the min-age cutoff.
            old_time = datetime.now(timezone.utc) - timedelta(days=9999)
            await session.execute(
                update(MemoryEmbedding)
                .where(MemoryEmbedding.task_id.in_(task_ids))
                .values(created_at=old_time)
            )
            await session.commit()

        monkeypatch.setenv("MEMORY_EMBEDDINGS_CONSOLIDATION_MAX_GROUPS_PER_CYCLE", "1")
        monkeypatch.setenv("MEMORY_EMBEDDINGS_CONSOLIDATION_MIN_AGE_DAYS", "1")
        monkeypatch.setenv(
            "MEMORY_EMBEDDINGS_CONSOLIDATION_SIMILARITY_THRESHOLD", "0.99"
        )
        monkeypatch.setenv("MEMORY_EMBEDDINGS_CONSOLIDATION_MIN_GROUP_SIZE", "2")
        reset_settings_cache()
        try:
            with patch("anthropic.Anthropic") as mock_cls:
                mock_client = MagicMock()
                mock_client.messages.create.return_value = _mock_anthropic_response(
                    "merged"
                )
                mock_cls.return_value = mock_client

                merged_count = await run_memory_consolidation_cycle()

            assert merged_count <= 1
            assert mock_client.messages.create.call_count <= 1
        finally:
            reset_settings_cache()
    finally:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id.in_(task_ids))
            )
            await session.commit()
        await engine.dispose()
