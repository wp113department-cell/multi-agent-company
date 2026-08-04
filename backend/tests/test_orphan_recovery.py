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
                    # Stage 4 Cluster N production validation (2026-08-04) —
                    # must stay timezone-AWARE, matching the real
                    # heartbeat_agent_run()'s own datetime.now(timezone.utc)
                    # convention and reconcile_orphaned_runs()'s now-fixed
                    # cutoff computation. A naive value here previously
                    # masked a real bug: this environment's system timezone
                    # (Asia/Kolkata, UTC+5:30) causes the DB driver to
                    # silently reinterpret a naive datetime as local time,
                    # not UTC -- confirmed directly (a naive "UTC-intended"
                    # write round-tripped back shifted by exactly -5:30).
                    # Previously that shift happened on both this fixture's
                    # write AND reconcile_orphaned_runs()'s own (also-naive)
                    # cutoff, so it canceled out by coincidence; fixing only
                    # one side breaks the other, so both are now aware.
                    stale_at = datetime.now(timezone.utc) - timedelta(
                        seconds=heartbeat_age_seconds
                    )
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


def test_a_real_heartbeat_write_is_correctly_recognized_as_stale() -> None:
    """Stage 4 Cluster N production validation (2026-08-04) — regression
    guard for a real bug a live E2E test caught: reconcile_orphaned_runs()'s
    cutoff used to be computed as a NAIVE datetime
    (`.replace(tzinfo=None)`), which this environment's DB driver silently
    reinterprets as SYSTEM-LOCAL time (this sandbox runs Asia/Kolkata,
    UTC+5:30), not UTC, when bound as a raw-SQL comparison parameter —
    confirmed directly: a naive "UTC-intended" write round-tripped back
    shifted by exactly -5:30. This was invisible in every pre-existing test
    because _make_agent_run's own fixture ALSO wrote its stale timestamp
    using the same naive convention, so the erroneous shift canceled out on
    both sides of the comparison by coincidence — masking the bug until a
    real, correctly timezone-aware write (from the actual production
    heartbeat_agent_run_sync(), not a test fixture backdating a fake
    timestamp) was compared against it for the first time.

    This test uses the REAL public sync bridge (heartbeat_agent_run_sync,
    the exact function run_agent_graph()'s execute_tools node calls) to
    write a real "now" heartbeat, waits past a short real threshold, then
    proves the sweep correctly reconciles it — closing the gap between "the
    fixture's synthetic stale timestamp is reconciled" (already covered
    above) and "a REAL heartbeat write, once genuinely stale, is
    reconciled" (what actually matters in production)."""
    import time

    from app.db.repository import heartbeat_agent_run_sync
    from app.fleet.failure_ladder import reconcile_orphaned_runs

    task_id, run_id = _make_agent_run("running", heartbeat_age_seconds=None)
    try:
        heartbeat_agent_run_sync(run_id)  # the real production write path
        run = _get_run(run_id)
        assert run.last_heartbeat_at is not None  # type: ignore[attr-defined]

        time.sleep(2.2)  # genuinely age past the 2s threshold below
        _reset_shared_engine()
        reconciled = asyncio.run(reconcile_orphaned_runs(threshold_seconds=2))
        assert reconciled >= 1

        run = _get_run(run_id)
        assert run.status == "failed"  # type: ignore[attr-defined]
    finally:
        _cleanup(task_id)
