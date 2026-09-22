"""T2-B2 (2026-09-22, GRIDIRON_PARTIAL #235/#236/#246) — real-DB proof that
reconcile_orphaned_runs() genuinely resumes a covered orphan through
app.fleet.resume_registry instead of unconditionally marking it "failed"
(the pre-existing behavior for every orphan, still correct for anything this
registry doesn't cover — see the second test below).

Matches tests/test_orphan_recovery.py's own real-DB convention (this
sandbox has a real Postgres available) rather than mocking the DB for
something this state-sensitive.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.db.repository import create_agent_run, create_task


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _make_stale_agent_run(agent_type: str, description: str = "desc") -> tuple[int, str]:
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentRun

    async def _run() -> tuple[int, str]:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                task = await create_task(session, "t2b2 orphan resume task", description)
                run = await create_agent_run(
                    session,
                    task.id,
                    agent_type,
                    "claude-sonnet-5",
                    trace_id=f"t2b2-orphan-{task.id}",
                )
                stale_at = datetime.now(timezone.utc) - timedelta(seconds=1200)
                await session.execute(
                    update(AgentRun)
                    .where(AgentRun.id == run.id)
                    .values(last_heartbeat_at=stale_at)
                )
                await session.commit()
                return task.id, run.id
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


def _get_run(run_id: str) -> object:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentRun

    async def _run() -> object:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                result = await session.execute(
                    select(AgentRun).where(AgentRun.id == run_id)
                )
                return result.scalar_one()
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


def _reset_shared_engine() -> None:
    import app.db.session as _sess

    _sess._engine = None
    _sess._session_factory = None


def test_orphan_with_a_covered_agent_type_is_resumed_not_failed_real_db() -> None:
    task_id, run_id = _make_stale_agent_run("bug_fix", description="fix the login bug")
    try:
        from app.fleet.failure_ladder import reconcile_orphaned_runs

        _reset_shared_engine()
        with patch("app.agents.bug_fix.run_bug_fix", autospec=True) as mock_run:
            reconciled = asyncio.run(reconcile_orphaned_runs(threshold_seconds=900))
            assert reconciled >= 1

            # asyncio.create_task() inside reconcile_orphaned_runs schedules
            # the dispatch on THIS loop — asyncio.run() has already torn the
            # loop down by the time we get here, so the task itself won't
            # have run to completion, but the row's own status is decided
            # BEFORE that dispatch is scheduled (this test's real point):
            run = _get_run(run_id)
            assert run.status == "running"  # type: ignore[attr-defined]
            assert run.error is None  # type: ignore[attr-defined]
    finally:
        _cleanup(task_id)


def test_orphan_with_an_uncovered_agent_type_is_still_marked_failed_real_db() -> None:
    """security_reviewer has no resume_trace_id support in this batch —
    must fall back to today's exact pre-existing behavior."""
    task_id, run_id = _make_stale_agent_run("security_reviewer")
    try:
        from app.fleet.failure_ladder import reconcile_orphaned_runs

        _reset_shared_engine()
        reconciled = asyncio.run(reconcile_orphaned_runs(threshold_seconds=900))
        assert reconciled >= 1

        run = _get_run(run_id)
        assert run.status == "failed"  # type: ignore[attr-defined]
        assert "orphaned" in (run.error or "")  # type: ignore[attr-defined]
    finally:
        _cleanup(task_id)


def test_orphan_with_no_trace_id_is_still_marked_failed_real_db() -> None:
    """A covered agent_type with no trace_id (legacy row, or AgentRun
    tracking that never linked one) has nothing to resume FROM — must fall
    back exactly like the uncovered case."""
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentRun

    task_id, run_id = _make_stale_agent_run("bug_fix")

    async def _clear_trace_id() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(
                    update(AgentRun).where(AgentRun.id == run_id).values(trace_id=None)
                )
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_clear_trace_id())

    try:
        from app.fleet.failure_ladder import reconcile_orphaned_runs

        _reset_shared_engine()
        reconciled = asyncio.run(reconcile_orphaned_runs(threshold_seconds=900))
        assert reconciled >= 1

        run = _get_run(run_id)
        assert run.status == "failed"  # type: ignore[attr-defined]
    finally:
        _cleanup(task_id)
