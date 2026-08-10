"""Batch 2 audit gap-closure (§2 "Duplicate work prevented") —
app/pipeline/file_locks.py.

conflict_guard.check_file_conflicts() was only ever a point-in-time READ,
not a held lock: a second epic's own check could still race in during the
gap before this epic's own conflict_check_node finished. These tests prove
reserve_epic_files()/release_epic_files() against the REAL Postgres dev DB
(same isolated-engine convention as test_phase51_epic_manager_graph.py):
1. two epics can never both hold a lock on the same file (real UNIQUE
   constraint enforcement, not app-level timing);
2. a losing epic's attempt leaves NO partial locks behind (all-or-nothing
   SAVEPOINT semantics);
3. release actually frees the file for a later epic;
4. an expired lock (TTL) is treated as not held, so a crashed epic can't
   permanently deadlock a file.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import EpicFileLock


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _cleanup_locks(*epic_ids: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            await session.execute(
                delete(EpicFileLock).where(EpicFileLock.epic_id.in_(epic_ids))
            )
            await session.commit()
    finally:
        await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_reserve_then_second_epic_conflicts_on_same_file() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.pipeline.file_locks import reserve_epic_files

    epic_a = f"test-lock-a-{uuid.uuid4()}"
    epic_b = f"test-lock-b-{uuid.uuid4()}"
    path = f"app/some_module_{uuid.uuid4().hex[:8]}.py"

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            conflict_a = await reserve_epic_files([path], epic_a, session)
            await session.commit()
        assert conflict_a is None

        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            conflict_b = await reserve_epic_files([path], epic_b, session)
            await session.commit()
        assert conflict_b is not None
        assert epic_a in conflict_b
        assert path in conflict_b
    finally:
        await engine.dispose()  # type: ignore[attr-defined]
        await _cleanup_locks(epic_a, epic_b)


@pytest.mark.asyncio
async def test_losing_reserve_leaves_no_partial_locks() -> None:
    """epic_b requests [free_file, contested_file] — contested_file is
    already held by epic_a. epic_b's whole reserve must fail AND leave
    free_file unlocked too (all-or-nothing), not partially acquired."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.pipeline.file_locks import reserve_epic_files

    epic_a = f"test-lock-a-{uuid.uuid4()}"
    epic_b = f"test-lock-b-{uuid.uuid4()}"
    free_file = f"app/free_{uuid.uuid4().hex[:8]}.py"
    contested_file = f"app/contested_{uuid.uuid4().hex[:8]}.py"

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            conflict_a = await reserve_epic_files([contested_file], epic_a, session)
            await session.commit()
        assert conflict_a is None

        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            conflict_b = await reserve_epic_files(
                [free_file, contested_file], epic_b, session
            )
            await session.commit()
        assert conflict_b is not None

        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            rows = (
                await session.execute(
                    select(EpicFileLock).where(EpicFileLock.file_path == free_file)
                )
            ).scalars().all()
        assert rows == [], "losing reserve must not leave the free file locked"
    finally:
        await engine.dispose()  # type: ignore[attr-defined]
        await _cleanup_locks(epic_a, epic_b)


@pytest.mark.asyncio
async def test_release_frees_the_file_for_a_later_epic() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.pipeline.file_locks import release_epic_files, reserve_epic_files

    epic_a = f"test-lock-a-{uuid.uuid4()}"
    epic_b = f"test-lock-b-{uuid.uuid4()}"
    path = f"app/released_{uuid.uuid4().hex[:8]}.py"

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            assert await reserve_epic_files([path], epic_a, session) is None
            await session.commit()

        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            await release_epic_files(epic_a, session)
            await session.commit()

        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            conflict_b = await reserve_epic_files([path], epic_b, session)
            await session.commit()
        assert conflict_b is None, "file must be free after release"
    finally:
        await engine.dispose()  # type: ignore[attr-defined]
        await _cleanup_locks(epic_a, epic_b)


@pytest.mark.asyncio
async def test_expired_lock_is_treated_as_not_held() -> None:
    """Simulates a crashed epic: a lock row whose expires_at is already in
    the past must not permanently block a later epic's reserve."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.pipeline.file_locks import reserve_epic_files

    stale_epic = f"test-lock-stale-{uuid.uuid4()}"
    new_epic = f"test-lock-new-{uuid.uuid4()}"
    path = f"app/stale_{uuid.uuid4().hex[:8]}.py"

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            session.add(
                EpicFileLock(
                    epic_id=stale_epic,
                    file_path=path,
                    expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
                )
            )
            await session.commit()

        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            conflict = await reserve_epic_files([path], new_epic, session)
            await session.commit()
        assert conflict is None, "expired lock must not block a new reserve"
    finally:
        await engine.dispose()  # type: ignore[attr-defined]
        await _cleanup_locks(stale_epic, new_epic)


@pytest.mark.asyncio
async def test_empty_candidate_list_is_a_no_op() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.pipeline.file_locks import reserve_epic_files

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            assert await reserve_epic_files([], "no-op-epic", session) is None
    finally:
        await engine.dispose()  # type: ignore[attr-defined]
