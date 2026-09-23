"""T2-B6 (2026-09-22, GRIDIRON_PARTIAL #383 "Full cross-repo isolation
(every table)").

events/artifacts/pending_approvals/epic_scratchpad were the remaining
tables with no repo_id at all. Migration 053 added the column (NULL =
unscoped/legacy, same convention as migration 043's own repo_id columns);
this proves the real opportunistic population at each of the 4 write sites,
using the real Postgres DB.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Artifact, DevTask, Epic, EpicScratchpad, Event, PendingApproval, Repo


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _make_repo(session: AsyncSession, suffix: str) -> Repo:
    repo = Repo(
        github_url=f"https://github.com/test/t2b6-{suffix}",
        name=f"t2b6-{suffix}",
        local_path=f"/tmp/t2b6-{suffix}",
        status="ready",
    )
    session.add(repo)
    await session.flush()
    return repo


async def _make_task(session: AsyncSession, repo_id: int) -> DevTask:
    task = DevTask(title="t2b6 task", description="d", status="blocked", repo_id=repo_id)
    session.add(task)
    await session.flush()
    return task


@pytest.mark.asyncio
async def test_artifact_repo_id_is_populated_from_the_real_task() -> None:
    from app.artifacts.store import save_artifact_async

    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo = await _make_repo(session, suffix)
            task = await _make_task(session, repo.id)
            await session.commit()

            record = await save_artifact_async(
                task.id, "plan", "some content", "test_agent", db=session
            )

            row = (
                await session.execute(
                    select(Artifact).where(Artifact.artifact_id == record.artifact_id)
                )
            ).scalar_one()
            assert row.repo_id == repo.id

            await session.execute(delete(Artifact).where(Artifact.artifact_id == record.artifact_id))
            await session.execute(delete(DevTask).where(DevTask.id == task.id))
            await session.execute(delete(Repo).where(Repo.id == repo.id))
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_artifact_repo_id_is_none_for_a_synthetic_task_id() -> None:
    from app.artifacts.store import save_artifact_async

    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            record = await save_artifact_async(
                "fleet-scan-synthetic", "plan", "x", "test_agent", db=session
            )
            row = (
                await session.execute(
                    select(Artifact).where(Artifact.artifact_id == record.artifact_id)
                )
            ).scalar_one()
            assert row.repo_id is None

            await session.execute(delete(Artifact).where(Artifact.artifact_id == record.artifact_id))
            await session.commit()
    finally:
        await engine.dispose()


def test_pending_approval_repo_id_is_populated_from_the_real_task() -> None:
    from app.fleet.approval_gate import record_pending

    async def _setup() -> tuple[int, int]:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                repo = await _make_repo(session, uuid.uuid4().hex[:8])
                task = await _make_task(session, repo.id)
                await session.commit()
                return task.id, repo.id
        finally:
            await engine.dispose()

    task_id, repo_id = asyncio.run(_setup())
    thread_id = f"t2b6-pending-{uuid.uuid4().hex[:8]}"
    try:
        record_pending(thread_id, "plan_review", agent_name="test", task_id=task_id)

        async def _check() -> None:
            engine = _engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    row = (
                        await session.execute(
                            select(PendingApproval).where(
                                PendingApproval.thread_id == thread_id
                            )
                        )
                    ).scalar_one()
                    assert row.repo_id == repo_id
            finally:
                await engine.dispose()

        asyncio.run(_check())
    finally:

        async def _cleanup() -> None:
            engine = _engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    await session.execute(
                        delete(PendingApproval).where(PendingApproval.thread_id == thread_id)
                    )
                    await session.execute(delete(DevTask).where(DevTask.id == task_id))
                    await session.execute(delete(Repo).where(Repo.id == repo_id))
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(_cleanup())


@pytest.mark.asyncio
async def test_epic_scratchpad_repo_id_is_populated_from_the_real_epic() -> None:
    from app.fleet.scratchpad import write_entry

    engine = _engine()
    epic_id = str(uuid.uuid4())
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo = await _make_repo(session, suffix)
            session.add(
                Epic(
                    epic_id=epic_id,
                    title="t2b6 epic",
                    description="d",
                    status="pending",
                    repo_id=repo.id,
                )
            )
            await session.commit()

            ok = await write_entry(epic_id, "finding", {"x": 1}, "test_agent", session)
            assert ok is True

            row = (
                await session.execute(
                    select(EpicScratchpad).where(
                        EpicScratchpad.epic_id == epic_id, EpicScratchpad.key == "finding"
                    )
                )
            ).scalar_one()
            assert row.repo_id == repo.id

            await session.execute(delete(EpicScratchpad).where(EpicScratchpad.epic_id == epic_id))
            await session.execute(delete(Epic).where(Epic.epic_id == epic_id))
            await session.execute(delete(Repo).where(Repo.id == repo.id))
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_event_repo_id_is_populated_from_the_real_task() -> None:
    from app.event_bus.bus import publish_event
    from app.event_bus.models import GridironEvent

    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo = await _make_repo(session, suffix)
            task = await _make_task(session, repo.id)
            await session.commit()

            event_id = str(uuid.uuid4())
            await publish_event(
                GridironEvent(
                    event_id=event_id,
                    event_type="task.created",
                    task_id=str(task.id),
                    epic_id=None,
                    payload={},
                    emitted_by="test",
                ),
                db=session,
            )

            row = (
                await session.execute(select(Event).where(Event.event_id == event_id))
            ).scalar_one()
            assert row.repo_id == repo.id

            await session.execute(delete(Event).where(Event.event_id == event_id))
            await session.execute(delete(DevTask).where(DevTask.id == task.id))
            await session.execute(delete(Repo).where(Repo.id == repo.id))
            await session.commit()
    finally:
        await engine.dispose()
