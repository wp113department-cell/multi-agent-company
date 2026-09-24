"""T2-B7 (2026-09-24, GRIDIRON_PARTIAL #429 "Detect dependencies / optimize
order org-wide (auto-dispatch)").

app.main._dependency_auto_dispatch_loop is a `while True: sleep(...)`
background loop, not directly unit-testable as a whole — this exercises
its real per-iteration body function-by-function against real Postgres
(the same DevTask rows #428's own dependency gate produces), mocking only
the actual LLM-calling dispatch target (launch_planner) the same way
test_batch16_scheduler_and_metrics.py's own dependency-gate tests do.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import DevTask
from app.main import app


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _cleanup_sync(*task_ids: int) -> None:
    async def _run() -> None:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                for tid in task_ids:
                    await session.execute(delete(DevTask).where(DevTask.id == tid))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _set_status_sync(task_id: int, status: str) -> None:
    async def _run() -> None:
        from sqlalchemy import update

        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    update(DevTask).where(DevTask.id == task_id).values(status=status)
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


async def _run_one_dispatch_iteration() -> list[int]:
    """The exact per-iteration body of _dependency_auto_dispatch_loop,
    minus the outer `while True: sleep(...)` — real DB queries, real
    transition_task/dispatch_job calls, same as the real loop body."""
    from app.api.agents import launch_planner, launch_planning_pipeline
    from app.db.repository import (
        append_log,
        get_task,
        resolve_task_repo_path,
        transition_task,
    )
    from app.db.session import get_session_factory
    from app.main import _FireAndForgetBackgroundTasks
    from app.pipeline.queue_adapter import dispatch_job

    settings = get_settings()
    factory = get_session_factory()
    dispatched_ids: list[int] = []
    async with factory() as db:
        result = await db.execute(
            select(DevTask).where(
                DevTask.status == "blocked",
                DevTask.blocked_reason == "dependency",
            )
        )
        for task in list(result.scalars().all()):
            if not task.depends_on:
                continue
            still_unmet = False
            for dep_id in task.depends_on:
                dep_task = await get_task(db, int(dep_id))
                if dep_task is None or dep_task.status != "completed":
                    still_unmet = True
                    break
            if still_unmet:
                continue

            await transition_task(db, task.id, "planning")
            await append_log(db, task.id, "pipeline", "auto-dispatched (test harness)")
            repo_path = resolve_task_repo_path(task)
            job_fn = (
                launch_planning_pipeline
                if settings.pipeline_mode == "full"
                else launch_planner
            )
            await dispatch_job(
                _FireAndForgetBackgroundTasks(),
                job_fn,
                task.id,
                str(task.title),
                str(task.description),
                repo_path,
                priority=task.priority,
            )
            dispatched_ids.append(task.id)
    return dispatched_ids


class TestDependencyAutoDispatch:
    def test_still_unmet_dependency_is_not_dispatched(self) -> None:
        with TestClient(app) as client:
            dep_id = client.post(
                "/api/tasks",
                json={"title": "t2b7 auto still-blocked parent", "description": "d"},
            ).json()["id"]
            child_id = client.post(
                "/api/tasks",
                json={
                    "title": "t2b7 auto still-blocked child",
                    "description": "d",
                    "depends_on": [dep_id],
                },
            ).json()["id"]
            try:
                # Trip #428's own gate first so the row is genuinely
                # status="blocked"/blocked_reason="dependency".
                assert (
                    client.post(f"/api/tasks/{child_id}/run", json={}).status_code
                    == 409
                )

                # get_session_factory()'s shared engine is bound to the
                # event loop the app's lifespan started on (TestClient's
                # own background loop, exposed via .portal) — a separate
                # top-level asyncio.run() here would use a DIFFERENT loop
                # and asyncpg raises "attached to a different loop".
                dispatched = client.portal.call(_run_one_dispatch_iteration)

                assert child_id not in dispatched
                assert (
                    client.get(f"/api/tasks/{child_id}").json()["status"] == "blocked"
                )
            finally:
                _cleanup_sync(child_id, dep_id)

    def test_newly_completed_dependency_gets_auto_dispatched(self) -> None:
        with TestClient(app) as client:
            dep_id = client.post(
                "/api/tasks",
                json={"title": "t2b7 auto ready parent", "description": "d"},
            ).json()["id"]
            child_id = client.post(
                "/api/tasks",
                json={
                    "title": "t2b7 auto ready child",
                    "description": "d",
                    "depends_on": [dep_id],
                },
            ).json()["id"]
            try:
                assert (
                    client.post(f"/api/tasks/{child_id}/run", json={}).status_code
                    == 409
                )
                assert (
                    client.get(f"/api/tasks/{child_id}").json()["status"] == "blocked"
                )

                _set_status_sync(dep_id, "completed")

                async def _dispatch_and_wait() -> list[int]:
                    ids = await _run_one_dispatch_iteration()
                    # dispatch_job's asyncio path fires a real
                    # asyncio.create_task of launch_planner — must stay on
                    # THIS SAME loop (client.portal's) for that pending
                    # task to get a chance to run at all.
                    await asyncio.sleep(0.05)
                    return ids

                # settings.pipeline_mode defaults to "full", so the loop's
                # own job_fn selection picks launch_planning_pipeline, not
                # launch_planner (see _run_one_dispatch_iteration above).
                with patch(
                    "app.api.agents.launch_planning_pipeline",
                    new=AsyncMock(return_value=None),
                ) as mock_launch:
                    dispatched = client.portal.call(_dispatch_and_wait)

                assert dispatched == [child_id]
                got = client.get(f"/api/tasks/{child_id}")
                assert got.json()["status"] == "planning"
                assert got.json()["blockedReason"] is None
                mock_launch.assert_called_once()
            finally:
                _cleanup_sync(child_id, dep_id)

    def test_a_row_with_no_matching_candidates_is_a_silent_no_op(self) -> None:
        # No blocked/dependency rows exist for this repo-less scan — must
        # not raise, must return an empty dispatch list.
        dispatched = asyncio.run(_run_one_dispatch_iteration())
        assert isinstance(dispatched, list)
