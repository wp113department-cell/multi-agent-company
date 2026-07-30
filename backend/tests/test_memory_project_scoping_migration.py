"""Gap-closure Day 2 (answers.md root-cause 1a, migration 024) — real-DB proof
that MemoryEmbedding.repo_id / VersionedLesson.repo_id exist, are nullable
(NULL = unscoped/legacy, not a magic sentinel), preserve every pre-existing
row untouched, and correctly go NULL (not cascade-delete the memory row) when
their parent Repo is deleted — same ondelete=SET NULL convention dev_tasks.repo_id
already uses. Mirrors test_retention_archive.py's real-DB-not-mocked pattern
for this same table.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.models import MemoryEmbedding, Repo, VersionedLesson


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _make_repo(session: AsyncSession, suffix: str) -> int:
    repo = Repo(
        github_url=f"https://github.com/test/repo-{suffix}",
        name=f"repo-{suffix}",
        local_path=f"/tmp/repo-{suffix}",
        status="ready",
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return int(repo.id)


@pytest.mark.asyncio
async def test_repo_id_column_exists_and_is_nullable_on_both_tables() -> None:
    engine = _engine()
    try:
        async with engine.connect() as conn:
            for table in ("memory_embeddings", "versioned_lessons"):
                result = await conn.execute(
                    text(
                        "SELECT column_name, is_nullable FROM information_schema.columns "
                        "WHERE table_name = :table AND column_name = 'repo_id'"
                    ),
                    {"table": table},
                )
                rows = [tuple(row) for row in result.fetchall()]
                assert rows == [
                    ("repo_id", "YES")
                ], f"{table}.repo_id must exist and be nullable; got {rows}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_memory_embedding_repo_id_set_null_on_repo_delete_row_not_dropped() -> (
    None
):
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_id = await _make_repo(session, suffix)

            row = MemoryEmbedding(
                task_id=f"td-{suffix}",
                outcome="completed",
                category="task",
                description="scoped memory row for migration test",
                summary="summary",
                files_changed=[],
                repo_id=repo_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            row_id = row.id
            assert row.repo_id == repo_id

            # Delete the parent repo — FK ondelete=SET NULL must fire, the
            # memory row itself must survive.
            await session.execute(delete(Repo).where(Repo.id == repo_id))
            await session.commit()
            # expire_on_commit=False means the already-loaded `row` object
            # (still in this session's identity map) would otherwise be
            # handed back with its stale, pre-delete repo_id attribute
            # instead of the real post-delete DB value — force a real
            # re-read from Postgres, not the Python-side cache.
            session.expire_all()

            refetched = (
                await session.execute(
                    select(MemoryEmbedding).where(MemoryEmbedding.id == row_id)
                )
            ).scalar_one_or_none()
            assert (
                refetched is not None
            ), "memory row must NOT be deleted when its repo is deleted"
            assert (
                refetched.repo_id is None
            ), "repo_id must be SET NULL (unscoped/legacy), not left dangling"

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.id == row_id)
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_versioned_lesson_repo_id_set_null_on_repo_delete_row_not_dropped() -> (
    None
):
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_id = await _make_repo(session, suffix)

            lesson = VersionedLesson(
                lesson_id=f"lesson-{suffix}",
                topic="migration test topic",
                content="content",
                version=1,
                state="draft",
                repo_id=repo_id,
            )
            session.add(lesson)
            await session.commit()
            await session.refresh(lesson)
            lesson_row_id = lesson.id
            assert lesson.repo_id == repo_id

            await session.execute(delete(Repo).where(Repo.id == repo_id))
            await session.commit()
            session.expire_all()  # see comment in the MemoryEmbedding test above

            refetched = (
                await session.execute(
                    select(VersionedLesson).where(VersionedLesson.id == lesson_row_id)
                )
            ).scalar_one_or_none()
            assert (
                refetched is not None
            ), "lesson row must NOT be deleted when its repo is deleted"
            assert (
                refetched.repo_id is None
            ), "repo_id must be SET NULL (unscoped/legacy), not left dangling"

            await session.execute(
                delete(VersionedLesson).where(VersionedLesson.id == lesson_row_id)
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_unscoped_row_with_no_repo_id_is_a_real_null_not_a_sentinel_string() -> (
    None
):
    """A row written with no repo_id (the shape of every pre-migration row)
    must round-trip as Python None, not a magic string like "legacy"."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = MemoryEmbedding(
                task_id=f"td-unscoped-{suffix}",
                outcome="completed",
                category="task",
                description="unscoped legacy-shaped row",
                summary="summary",
                files_changed=[],
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            assert row.repo_id is None

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.id == row.id)
            )
            await session.commit()
    finally:
        await engine.dispose()
