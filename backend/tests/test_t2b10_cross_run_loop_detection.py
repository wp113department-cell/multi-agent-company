"""T2-B10 (2026-09-24, GRIDIRON_PARTIAL #442 "Detect looping agents
(cross-run)" — Task 1's own re-verification of this item, DOWNGRADED:
"only within-run stall detection exists [n_stalls] ... nothing detects
... an agent looping/failing repeatedly across runs.").

app/fleet/failure_ladder.py::_is_cross_run_looping() closes the cross-run
half of this gap (the same-tool-call-repeating half, within a single run,
would need ToolCallRecord to also track call arguments — a separate,
larger change not attempted here). Wired into reconcile_orphaned_runs():
an orphan whose (task_id, agent_type) has already failed
`cross_run_loop_window` times in a row is marked failed + escalated
instead of being auto-resumed yet again.

Real Postgres, no mocks for the DB itself.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import AgentRun
from app.db.repository import create_agent_run, create_task
from app.fleet.failure_ladder import _is_cross_run_looping, reconcile_orphaned_runs


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _seed_runs_sync(agent_type: str, statuses: list[str]) -> tuple[int, list[str]]:
    """Real task + one real AgentRun per status, oldest first, each
    started_at spaced a second apart so ORDER BY started_at DESC is
    unambiguous."""

    async def _run() -> tuple[int, list[str]]:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                task = await create_task(session, "td cross-run loop task", "desc")
                run_ids = []
                for i, status in enumerate(statuses):
                    run = await create_agent_run(session, task.id, agent_type, "m")
                    await session.execute(
                        update(AgentRun)
                        .where(AgentRun.id == run.id)
                        .values(
                            status=status,
                            started_at=datetime.now(timezone.utc)
                            - timedelta(seconds=len(statuses) - i),
                        )
                    )
                    run_ids.append(run.id)
                await session.commit()
                return task.id, run_ids
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


def _cleanup_sync(task_id: int) -> None:
    from sqlalchemy import delete

    from app.db.models import DevTask

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(
                    delete(AgentRun).where(AgentRun.task_id == task_id)
                )
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


class TestIsCrossRunLooping:
    def test_three_consecutive_failures_is_a_real_loop(self) -> None:
        task_id, _ = _seed_runs_sync("td_loop_agent", ["failed", "failed", "failed"])
        try:

            async def _check() -> bool:
                engine = _new_isolated_db_engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                        return await _is_cross_run_looping(
                            session, task_id, "td_loop_agent", window=3
                        )
                finally:
                    await engine.dispose()  # type: ignore[attr-defined]

            assert asyncio.run(_check()) is True
        finally:
            _cleanup_sync(task_id)

    def test_a_recent_success_among_the_window_is_not_a_loop(self) -> None:
        task_id, _ = _seed_runs_sync(
            "td_loop_agent2", ["failed", "completed", "failed"]
        )
        try:

            async def _check() -> bool:
                engine = _new_isolated_db_engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                        return await _is_cross_run_looping(
                            session, task_id, "td_loop_agent2", window=3
                        )
                finally:
                    await engine.dispose()  # type: ignore[attr-defined]

            assert asyncio.run(_check()) is False
        finally:
            _cleanup_sync(task_id)

    def test_fewer_runs_than_the_window_is_never_a_loop(self) -> None:
        # Real, honest "not enough history yet" — never a false positive.
        task_id, _ = _seed_runs_sync("td_loop_agent3", ["failed", "failed"])
        try:

            async def _check() -> bool:
                engine = _new_isolated_db_engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                        return await _is_cross_run_looping(
                            session, task_id, "td_loop_agent3", window=3
                        )
                finally:
                    await engine.dispose()  # type: ignore[attr-defined]

            assert asyncio.run(_check()) is False
        finally:
            _cleanup_sync(task_id)

    def test_exclude_run_id_omits_the_current_still_running_row(self) -> None:
        # The currently-evaluated orphan itself (still "running") must not
        # dilute its own PRIOR failure history — excluding it here still
        # correctly finds 3 real prior failures.
        task_id, run_ids = _seed_runs_sync(
            "td_loop_agent6", ["failed", "failed", "failed", "running"]
        )
        try:

            async def _check() -> bool:
                engine = _new_isolated_db_engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                        return await _is_cross_run_looping(
                            session,
                            task_id,
                            "td_loop_agent6",
                            window=3,
                            exclude_run_id=run_ids[-1],
                        )
                finally:
                    await engine.dispose()  # type: ignore[attr-defined]

            assert asyncio.run(_check()) is True
        finally:
            _cleanup_sync(task_id)

    def test_a_different_agent_type_on_the_same_task_is_not_conflated(self) -> None:
        task_id, _ = _seed_runs_sync("td_loop_agent4", ["failed", "failed", "failed"])
        try:

            async def _check() -> bool:
                engine = _new_isolated_db_engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                        return await _is_cross_run_looping(
                            session, task_id, "some_other_agent_type", window=3
                        )
                finally:
                    await engine.dispose()  # type: ignore[attr-defined]

            assert asyncio.run(_check()) is False
        finally:
            _cleanup_sync(task_id)


class TestOrphanRecoverySkipsLoopingAgents:
    def test_a_looping_orphan_is_failed_not_resumed(self) -> None:
        # Three PRIOR real failures for this exact (task, agent_type) —
        # satisfying the default cross_run_loop_window=3 on its own,
        # excluding the currently-stuck run itself — THEN a fourth run
        # left stuck "running" with a stale heartbeat: the real orphan-
        # recovery scenario, now hitting the loop guard before ever
        # attempting a resume.
        task_id, run_ids = _seed_runs_sync(
            "td_loop_agent5", ["failed", "failed", "failed", "running"]
        )
        stuck_run_id = run_ids[-1]
        try:

            async def _make_heartbeat_stale() -> None:
                engine = _new_isolated_db_engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                        await session.execute(
                            update(AgentRun)
                            .where(AgentRun.id == stuck_run_id)
                            .values(
                                last_heartbeat_at=datetime.now(timezone.utc)
                                - timedelta(seconds=10_000)
                            )
                        )
                        await session.commit()
                finally:
                    await engine.dispose()  # type: ignore[attr-defined]

            asyncio.run(_make_heartbeat_stale())

            # td_loop_agent5 is not a resume_registry-covered agent type,
            # so _try_resume_orphan would never have resumed it anyway —
            # the real thing under test is that reconcile_orphaned_runs()
            # detects the loop and marks it failed with the LOOP-specific
            # error message, not the generic orphan one, proving the loop
            # check actually ran and short-circuited before the normal
            # resume-attempt path.
            with patch("app.fleet.failure_ladder.escalate"):
                reconciled = asyncio.run(reconcile_orphaned_runs(threshold_seconds=1))
            assert reconciled >= 1

            async def _get_status() -> tuple[str, str | None]:
                engine = _new_isolated_db_engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                        row = await session.get(AgentRun, stuck_run_id)
                        assert row is not None
                        return row.status, row.error
                finally:
                    await engine.dispose()  # type: ignore[attr-defined]

            status, error = asyncio.run(_get_status())
            assert status == "failed"
            assert error is not None and "loop" in error.lower()
        finally:
            _cleanup_sync(task_id)
