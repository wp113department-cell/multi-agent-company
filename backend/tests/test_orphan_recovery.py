"""Real-DB tests for MASTER_AGENT_v2.md Phase 5.6 — orphan agent_run
recovery. A process crash mid-run stops AgentRun.last_heartbeat_at (already
real, A.9) from updating, but nothing previously noticed a stale heartbeat
and reconciled that run's status — confirmed by grep before this change (no
caller of AgentRun.status='failed' driven by heartbeat staleness anywhere).
Matches tests/test_retention_archive.py's own real-DB convention (this
sandbox has a real Postgres available, confirmed by that file already
passing) rather than mocking the DB for something this state-sensitive.
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


def _make_agent_run(status: str, heartbeat_age_seconds: int | None) -> tuple[int, str]:
    """Real task + real AgentRun row. heartbeat_age_seconds=None leaves
    last_heartbeat_at at its default (NULL) — a run that never even got its
    first heartbeat, which must NOT match a staleness comparison against
    NULL (SQL: NULL < anything is never true) — a run that hasn't started
    heartbeating yet is not the same thing as one that stopped."""
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentRun

    async def _run() -> tuple[int, str]:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                task = await create_task(session, "td orphan recovery task", "desc")
                run = await create_agent_run(
                    session, task.id, "td_orphan_test_agent", "claude-sonnet-5"
                )
                if status != "running":
                    await session.execute(
                        update(AgentRun)
                        .where(AgentRun.id == run.id)
                        .values(status=status)
                    )
                if heartbeat_age_seconds is not None:
                    stale_at = datetime.now(timezone.utc).replace(
                        tzinfo=None
                    ) - timedelta(seconds=heartbeat_age_seconds)
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
    """reconcile_orphaned_runs() uses the shared, process-wide
    get_session_factory() singleton by design (it's a real background loop
    in production) — reset it first so this test's own asyncio.run() gets a
    fresh engine bound to its own event loop, matching
    test_retention_archive.py's own documented fix for the same hazard."""
    import app.db.session as _sess

    _sess._engine = None
    _sess._session_factory = None


def test_stale_heartbeat_run_is_reconciled_to_failed_real_db() -> None:
    task_id, run_id = _make_agent_run("running", heartbeat_age_seconds=1200)
    try:
        from app.fleet.failure_ladder import reconcile_orphaned_runs

        _reset_shared_engine()
        reconciled = asyncio.run(reconcile_orphaned_runs(threshold_seconds=900))
        assert reconciled >= 1

        run = _get_run(run_id)
        assert run.status == "failed"  # type: ignore[attr-defined]
        assert "orphaned" in (run.error or "")  # type: ignore[attr-defined]
        assert run.finished_at is not None  # type: ignore[attr-defined]
    finally:
        _cleanup(task_id)


def test_fresh_heartbeat_run_is_left_alone_real_db() -> None:
    task_id, run_id = _make_agent_run("running", heartbeat_age_seconds=5)
    try:
        from app.fleet.failure_ladder import reconcile_orphaned_runs

        _reset_shared_engine()
        asyncio.run(reconcile_orphaned_runs(threshold_seconds=900))

        run = _get_run(run_id)
        assert run.status == "running"  # type: ignore[attr-defined]
        assert run.finished_at is None  # type: ignore[attr-defined]
    finally:
        _cleanup(task_id)


def test_never_heartbeated_run_is_left_alone_real_db() -> None:
    """A run with a NULL last_heartbeat_at (hasn't sent its first heartbeat
    yet) must not be swept as orphaned — NULL is not "stale", it's "not yet
    started reporting"."""
    task_id, run_id = _make_agent_run("running", heartbeat_age_seconds=None)
    try:
        from app.fleet.failure_ladder import reconcile_orphaned_runs

        _reset_shared_engine()
        asyncio.run(reconcile_orphaned_runs(threshold_seconds=900))

        run = _get_run(run_id)
        assert run.status == "running"  # type: ignore[attr-defined]
    finally:
        _cleanup(task_id)


def test_already_completed_run_is_left_alone_real_db() -> None:
    task_id, run_id = _make_agent_run("completed", heartbeat_age_seconds=1200)
    try:
        from app.fleet.failure_ladder import reconcile_orphaned_runs

        _reset_shared_engine()
        asyncio.run(reconcile_orphaned_runs(threshold_seconds=900))

        run = _get_run(run_id)
        assert run.status == "completed"  # type: ignore[attr-defined]
    finally:
        _cleanup(task_id)


def test_reconcile_escalates_each_orphan_through_failure_ladder() -> None:
    task_id, run_id = _make_agent_run("running", heartbeat_age_seconds=1200)
    try:
        from app.fleet.failure_ladder import reconcile_orphaned_runs

        _reset_shared_engine()
        with patch("app.fleet.failure_ladder.escalate") as mock_escalate:
            asyncio.run(reconcile_orphaned_runs(threshold_seconds=900))

        mock_escalate.assert_called_once()
        assert mock_escalate.call_args.args[0] == "td_orphan_test_agent"
        assert "orphaned" in mock_escalate.call_args.args[1]
    finally:
        _cleanup(task_id)


def test_orphan_sweep_disabled_when_threshold_is_zero() -> None:
    from app.fleet.failure_ladder import start_orphan_recovery_loop

    with patch("app.fleet.failure_ladder.get_settings") as mock_settings:
        mock_settings.return_value.agent_run_orphan_threshold_seconds = 0
        # Must return immediately (disabled), not enter the infinite loop —
        # if this hangs, the sweep isn't actually honoring the disable flag.
        asyncio.run(asyncio.wait_for(start_orphan_recovery_loop(), timeout=2.0))
