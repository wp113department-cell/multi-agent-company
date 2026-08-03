"""Stage 2 Day 42 — app/memory/store.py's real dedup guard for raw
memory_embeddings writes (answers.md Q120 "Automatic Memory Cleanup"/
"Shared Memory Synchronization": "remove duplicated memories: PARTIAL,
only VersionedLesson dedups; raw memory_embeddings rows are never
deduplicated"). Mirrors `app/fleet/versioned_memory.py::_find_most_similar_published`'s
real cosine-similarity-gated mechanism, adapted to MemoryEmbedding's
simpler shape (see _find_near_duplicate's own docstring for why).

Real-DB, content-derived signed fake vectors (see
test_memory_archived_filter.py's identical helper for why signed, not
uniform-positive, components are required for these similarity-sensitive
tests).
"""

from __future__ import annotations

import hashlib
import random
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from unittest.mock import patch

from app.config import get_settings, reset_settings_cache
from app.db.models import MemoryEmbedding, Repo
from app.memory.store import (
    embed_architecture_note,
    embed_task_outcome,
    record_memory_access,
)


def _vector_for(text_to_embed: str) -> list[float]:
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_near_duplicate_write_reuses_existing_row_not_inserted(
    _mock_embed: object,
) -> None:
    """The core behavior: writing the same content twice in the same
    category must not create two rows — the second write is recognized as
    a near-duplicate and the existing row's reuse signal is strengthened
    instead."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_first = f"td-gap42-dup-first-{suffix}"
    task_second = f"td-gap42-dup-second-{suffix}"
    marker = f"dedup near-duplicate marker {suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            first = await embed_task_outcome(
                task_id=task_first,
                description=marker,
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert first is not None
            assert first.reuse_count == 0

            second = await embed_task_outcome(
                task_id=task_second,
                description=marker,
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert second is not None
            # Same underlying row, not a new one — the near-duplicate write
            # was recognized and reused, not inserted as a second row.
            assert second.id == first.id
            assert second.task_id == task_first  # the original row's identity

            refetched = (
                await session.execute(
                    select(MemoryEmbedding).where(MemoryEmbedding.id == first.id)
                )
            ).scalar_one()
            assert refetched.reuse_count == 1  # strengthened by the dedup match

            # Confirm no second row was created under task_second at all.
            never_created = (
                await session.execute(
                    select(MemoryEmbedding).where(
                        MemoryEmbedding.task_id == task_second
                    )
                )
            ).scalar_one_or_none()
            assert never_created is None

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_first)
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_distinct_content_creates_distinct_rows(_mock_embed: object) -> None:
    """Genuinely different content must never be collapsed — dedup is a
    near-exact-duplicate guard, not a broad similarity merge."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_a = f"td-gap42-distinct-a-{suffix}"
    task_b = f"td-gap42-distinct-b-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row_a = await embed_task_outcome(
                task_id=task_a,
                description=f"dedup distinct content alpha {suffix}",
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            row_b = await embed_task_outcome(
                task_id=task_b,
                description=f"dedup distinct content bravo {suffix}",
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert row_a is not None and row_b is not None
            assert row_a.id != row_b.id
            assert row_a.task_id == task_a
            assert row_b.task_id == task_b

            await session.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id.in_([task_a, task_b])
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dedup_disabled_creates_genuine_duplicate_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Config-driven, not hardcoded: memory_dedup_enabled=False must
    restore the pre-Day-42 unconditional-insert behavior exactly."""
    monkeypatch.setenv("MEMORY_DEDUP_ENABLED", "false")
    reset_settings_cache()
    try:
        engine = _engine()
        suffix = uuid.uuid4().hex[:8]
        task_first = f"td-gap42-nodedup-first-{suffix}"
        task_second = f"td-gap42-nodedup-second-{suffix}"
        marker = f"dedup disabled marker {suffix}"
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                with patch("app.memory.store._embed", side_effect=_vector_for):
                    first = await embed_task_outcome(
                        task_id=task_first,
                        description=marker,
                        summary="s",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                    )
                    second = await embed_task_outcome(
                        task_id=task_second,
                        description=marker,
                        summary="s",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                    )
                assert first is not None and second is not None
                assert first.id != second.id  # dedup genuinely bypassed

                await session.execute(
                    delete(MemoryEmbedding).where(
                        MemoryEmbedding.task_id.in_([task_first, task_second])
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()
    finally:
        reset_settings_cache()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_dedup_is_scoped_by_category(_mock_embed: object) -> None:
    """A 'task' category write must not dedup-match an 'architecture'
    category row even if the content is identical — categories are
    semantically distinct record types, not near-duplicates of each
    other."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-gap42-catscope-task-{suffix}"
    arch_id = f"td-gap42-catscope-arch-{suffix}"
    marker = f"dedup category scope marker {suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            arch_row = await embed_architecture_note(
                task_id=arch_id, content=marker, db=session
            )
            assert arch_row is not None

            task_row = await embed_task_outcome(
                task_id=task_id,
                description=marker,
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert task_row is not None
            # A genuinely new row, not the architecture-category one.
            assert task_row.id != arch_row.id
            assert task_row.task_id == task_id

            await session.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id.in_([task_id, arch_id])
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_dedup_is_scoped_by_repo_id(_mock_embed: object) -> None:
    """Mirrors the existing repo_id-scoping guarantee (Stage 0 Days 2-4):
    identical content written under two different repos must NOT dedup
    against each other — each repo gets its own row."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_a = f"td-gap42-reposcope-a-{suffix}"
    task_b = f"td-gap42-reposcope-b-{suffix}"
    marker = f"dedup repo scope marker {suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = Repo(
                github_url=f"https://github.com/test/gap42-a-{suffix}",
                name=f"gap42-a-{suffix}",
                local_path=f"/tmp/gap42-a-{suffix}",
                status="ready",
            )
            repo_b = Repo(
                github_url=f"https://github.com/test/gap42-b-{suffix}",
                name=f"gap42-b-{suffix}",
                local_path=f"/tmp/gap42-b-{suffix}",
                status="ready",
            )
            session.add_all([repo_a, repo_b])
            await session.commit()
            await session.refresh(repo_a)
            await session.refresh(repo_b)

            row_a = await embed_task_outcome(
                task_id=task_a,
                description=marker,
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
                repo_id=repo_a.id,
            )
            row_b = await embed_task_outcome(
                task_id=task_b,
                description=marker,
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
                repo_id=repo_b.id,
            )
            assert row_a is not None and row_b is not None
            assert row_a.id != row_b.id
            assert row_a.task_id == task_a
            assert row_b.task_id == task_b

            await session.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id.in_([task_a, task_b])
                )
            )
            await session.execute(
                delete(Repo).where(Repo.id.in_([repo_a.id, repo_b.id]))
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_dedup_ignores_archived_rows(_mock_embed: object) -> None:
    """An archived row is no longer "live" memory — a new write matching
    its content should create a fresh row, not silently resurrect the
    archived one by strengthening it."""
    from sqlalchemy import text as sa_text

    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_archived = f"td-gap42-archignore-old-{suffix}"
    task_new = f"td-gap42-archignore-new-{suffix}"
    marker = f"dedup ignores archived marker {suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            old_row = await embed_task_outcome(
                task_id=task_archived,
                description=marker,
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert old_row is not None
            await session.execute(
                sa_text(
                    "UPDATE memory_embeddings SET archived = true, archived_at = now() "
                    "WHERE id = :id"
                ),
                {"id": old_row.id},
            )
            await session.commit()

            new_row = await embed_task_outcome(
                task_id=task_new,
                description=marker,
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert new_row is not None
            assert new_row.id != old_row.id
            assert new_row.task_id == task_new

            await session.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id.in_([task_archived, task_new])
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_find_near_duplicate_direct_empty_list_when_dedup_disabled() -> None:
    """Direct unit coverage of the helper itself: dedup disabled short-
    circuits before ever touching the DB."""
    from app.memory.store import _find_near_duplicate

    original = get_settings().memory_dedup_enabled
    try:
        import os

        os.environ["MEMORY_DEDUP_ENABLED"] = "false"
        reset_settings_cache()
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await _find_near_duplicate([0.1] * 1536, "task", None, session)
                assert result is None
        finally:
            await engine.dispose()
    finally:
        os.environ["MEMORY_DEDUP_ENABLED"] = str(original)
        reset_settings_cache()


@pytest.mark.asyncio
async def test_record_memory_access_called_on_dedup_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies dedup's reuse-strengthening goes through the same real
    record_memory_access() path Day 40 built, not a separate ad hoc
    increment — one mechanism for "this memory was used again"."""
    from unittest.mock import AsyncMock

    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_first = f"td-gap42-recordaccess-first-{suffix}"
    task_second = f"td-gap42-recordaccess-second-{suffix}"
    marker = f"dedup record-access marker {suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            with patch("app.memory.store._embed", side_effect=_vector_for):
                first = await embed_task_outcome(
                    task_id=task_first,
                    description=marker,
                    summary="s",
                    outcome="completed",
                    files_changed=[],
                    db=session,
                )
                assert first is not None

                spy = AsyncMock(wraps=record_memory_access)
                with patch("app.memory.store.record_memory_access", spy):
                    second = await embed_task_outcome(
                        task_id=task_second,
                        description=marker,
                        summary="s",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                    )
                assert second is not None
                assert second.id == first.id
                spy.assert_awaited_once_with([first.id], session)

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_first)
            )
            await session.commit()
    finally:
        await engine.dispose()
