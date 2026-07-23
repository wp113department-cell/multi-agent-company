"""Gap-closure (files/GAPS_ALL_FILES_REPORT.md, 2026-07-23) — real-DB
verification that retention.py's archive-not-delete rewrite actually works
against Postgres, not just mocks (test_final_session.py covers the mocked
unit-level behavior). Specifically exercises the naive-vs-timezone-aware
datetime handling directly against asyncpg, since a prior gap-closure found
this exact class of bug (asyncpg raises DataError writing a tz-aware
datetime into a naive TIMESTAMP WITHOUT TIME ZONE column) undetected by
mocked tests alone.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.db.repository import create_task, list_logs


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _make_task_with_old_log() -> tuple[int, int]:
    """A task with one TaskLog row backdated 200 days (older than any
    realistic retention window) and one fresh row — real INSERT, real DB."""
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import TaskLog

    async def _run() -> tuple[int, int]:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                task = await create_task(session, "td retention task", "desc")

                old_log = TaskLog(task_id=task.id, category="test", message="old entry")
                fresh_log = TaskLog(
                    task_id=task.id, category="test", message="fresh entry"
                )
                session.add_all([old_log, fresh_log])
                await session.commit()
                await session.refresh(old_log)

                old_cutoff = datetime.now(timezone.utc).replace(
                    tzinfo=None
                ) - timedelta(days=200)
                await session.execute(
                    update(TaskLog)
                    .where(TaskLog.id == old_log.id)
                    .values(created_at=old_cutoff)
                )
                await session.commit()
                return task.id, old_log.id
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


def _cleanup(task_id: int) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_enforce_retention_archives_old_row_and_keeps_fresh_row_real_db() -> None:
    task_id, old_log_id = _make_task_with_old_log()
    try:
        with patch("app.services.retention.get_settings") as mock_settings:
            mock_settings.return_value.log_retention_days = 90

            async def _run() -> int:
                # enforce_retention_policy() uses the shared, process-wide
                # get_session_factory() singleton (by design — it's a real
                # background loop in production, not test-isolated). Reset it
                # first so this test's own asyncio.run() gets a fresh engine
                # bound to its own event loop, matching the documented
                # shared-engine hazard fix used elsewhere in this suite
                # (tests/pending/conftest.py's reset_db_engine fixture).
                import app.db.session as _sess

                _sess._engine = None
                _sess._session_factory = None

                from app.services.retention import enforce_retention_policy

                return await enforce_retention_policy()

            archived_count = asyncio.run(_run())

        assert archived_count >= 1

        async def _check() -> None:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    # Default list_logs() excludes the archived row.
                    visible = await list_logs(session, task_id)
                    assert all(lg.id != old_log_id for lg in visible)
                    assert any(lg.message == "fresh entry" for lg in visible)

                    # include_archived=True brings it back.
                    with_archived = await list_logs(
                        session, task_id, include_archived=True
                    )
                    archived_row = next(
                        lg for lg in with_archived if lg.id == old_log_id
                    )
                    assert archived_row.archived is True
                    assert archived_row.archived_at is not None
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        asyncio.run(_check())
    finally:
        _cleanup(task_id)
