"""Stage 2 Day 39 — app/pipeline/cost_controller.py's new
estimated_duration_seconds field (answers.md Q42, "expected runtime
estimate: NO" -> real). Real-DB-backed test proving the historical branch
(reused from app.fleet.size_estimate.historical_avg_duration_seconds, the
same query Days 37-38 already built) actually activates, not just that the
SQL compiles.
"""

from __future__ import annotations

import datetime
import uuid

from app.pipeline.cost_controller import estimate_epic_cost


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _make_task() -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            task = DevTask(
                title="td gap39 cost duration test", description="d", status="pending"
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)
            return int(task.id)
    finally:
        await engine.dispose()  # type: ignore[attr-defined]


async def _cleanup_task(task_id: int) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentRun, DevTask

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            await session.execute(delete(AgentRun).where(AgentRun.task_id == task_id))
            await session.execute(delete(DevTask).where(DevTask.id == task_id))
            await session.commit()
    finally:
        await engine.dispose()  # type: ignore[attr-defined]


async def test_estimate_epic_cost_uses_real_historical_duration_when_present() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentRun

    task_id = await _make_task()
    try:
        engine = _new_isolated_db_engine()
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                # Two completed 'coder' runs: 60s and 90s -> real avg 75s.
                session.add_all(
                    [
                        AgentRun(
                            id=str(uuid.uuid4()),
                            task_id=task_id,
                            agent_type="coder",
                            status="completed",
                            started_at=now - datetime.timedelta(seconds=60),
                            finished_at=now,
                        ),
                        AgentRun(
                            id=str(uuid.uuid4()),
                            task_id=task_id,
                            agent_type="coder",
                            status="completed",
                            started_at=now - datetime.timedelta(seconds=90),
                            finished_at=now,
                        ),
                    ]
                )
                await session.commit()

                estimate = await estimate_epic_cost(subtask_count=2, db=session)
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

        assert estimate.duration_source == "historical"
        # 75s average x 2 subtasks = 150s.
        assert abs(estimate.estimated_duration_seconds - 150.0) < 1.0
    finally:
        await _cleanup_task(task_id)


async def test_estimate_epic_cost_falls_back_when_no_coder_history_exists() -> None:
    from app.config import get_settings

    task_id = await _make_task()
    try:
        engine = _new_isolated_db_engine()
        try:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                estimate = await estimate_epic_cost(subtask_count=3, db=session)
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

        settings = get_settings()
        assert estimate.duration_source == "config_fallback"
        assert estimate.estimated_duration_seconds == (
            settings.size_processing_seconds_fallback_per_subtask * 3
        )
    finally:
        await _cleanup_task(task_id)
