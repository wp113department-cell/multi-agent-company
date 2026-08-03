"""Stage 2 Day 37 — app/fleet/size_estimate.py (answers.md Q32, Project/Repo
Size Awareness). Real filesystem measurement plus real-DB-backed historical
calibration tests, per the project's established verify-empirically
discipline: at least one test measures this actual checked-out repo
directory, and the historical branch is proven against real inserted
`agent_runs` rows, not just asserted by reading the SQL.
"""

from __future__ import annotations

import datetime
import os
import uuid

import pytest

from app.fleet.size_estimate import (
    RepoSizeSummary,
    SizeEstimate,
    estimate_project_size,
    measure_repo_size,
)


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
                title="td gap37 size estimate test", description="d", status="pending"
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


def test_measure_repo_size_against_this_real_checked_out_directory() -> None:
    """No mocking — walks the real app/fleet/ directory of this repo."""
    result = measure_repo_size("app/fleet")

    assert isinstance(result, RepoSizeSummary)
    assert result.total_files > 0
    assert result.total_size_bytes > 0
    assert result.total_size_mb == result.total_size_bytes / (1024**2)
    assert ".py" in result.ext_counts
    assert result.ext_counts[".py"] >= 10  # this package has well over 10 modules
    # Cross-check against an independent recursive count, proving a real
    # walk, not a fabricated/hardcoded number.
    real_py_count = sum(
        1
        for dirpath, dirnames, filenames in os.walk("app/fleet")
        for f in filenames
        if f.endswith(".py")
    )
    assert result.ext_counts[".py"] == real_py_count


def test_measure_repo_size_excludes_conventional_junk_dirs(tmp_path: object) -> None:
    import pathlib

    root = pathlib.Path(str(tmp_path))
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print(1)\n")
    (root / ".venv").mkdir()
    (root / ".venv" / "should_not_count.py").write_text("x = 1\n")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "should_not_count.js").write_text("x = 1;\n")

    result = measure_repo_size(str(root))

    assert result.total_files == 1
    assert result.ext_counts == {".py": 1}


@pytest.mark.asyncio
async def test_estimate_project_size_no_db_uses_config_fallback_for_processing() -> (
    None
):
    est = await estimate_project_size("app/fleet", db=None)

    assert isinstance(est, SizeEstimate)
    assert est.processing_source == "config_fallback"
    assert est.test_execution_source == "config_fallback"
    assert est.estimated_disk_required_mb > 0
    assert est.estimated_memory_required_mb > 0
    assert est.estimated_indexing_seconds > 0
    assert est.estimated_embedding_seconds > 0
    assert est.estimated_processing_seconds > 0
    assert est.estimated_test_execution_seconds > 0


@pytest.mark.asyncio
async def test_estimate_project_size_scales_processing_by_subtask_count() -> None:
    one = await estimate_project_size("app/fleet", db=None, subtask_count=1)
    five = await estimate_project_size("app/fleet", db=None, subtask_count=5)

    assert (
        abs(five.estimated_processing_seconds - one.estimated_processing_seconds * 5)
        < 1e-9
    )


@pytest.mark.asyncio
async def test_estimate_project_size_uses_real_historical_average_when_present() -> (
    None
):
    """Inserts real completed 'coder' AgentRun rows with known durations and
    proves the historical branch actually activates and computes the real
    average — not just that the SQL compiles."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentRun

    task_id = await _make_task()
    try:
        engine = _new_isolated_db_engine()
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                # Two completed 'coder' runs: 100s and 200s -> real avg 150s.
                session.add_all(
                    [
                        AgentRun(
                            id=str(uuid.uuid4()),
                            task_id=task_id,
                            agent_type="coder",
                            status="completed",
                            started_at=now - datetime.timedelta(seconds=100),
                            finished_at=now,
                        ),
                        AgentRun(
                            id=str(uuid.uuid4()),
                            task_id=task_id,
                            agent_type="coder",
                            status="completed",
                            started_at=now - datetime.timedelta(seconds=200),
                            finished_at=now,
                        ),
                    ]
                )
                await session.commit()

                est = await estimate_project_size(
                    "app/fleet", db=session, subtask_count=1
                )
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

        assert est.processing_source == "historical"
        assert abs(est.estimated_processing_seconds - 150.0) < 1.0
    finally:
        await _cleanup_task(task_id)


@pytest.mark.asyncio
async def test_estimate_project_size_ignores_non_coder_and_incomplete_runs() -> None:
    """A 'planner' run and an in-progress 'coder' run (no finished_at) must
    not pollute the 'coder' historical average."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentRun

    task_id = await _make_task()
    try:
        engine = _new_isolated_db_engine()
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                session.add_all(
                    [
                        AgentRun(
                            id=str(uuid.uuid4()),
                            task_id=task_id,
                            agent_type="planner",
                            status="completed",
                            started_at=now - datetime.timedelta(seconds=9999),
                            finished_at=now,
                        ),
                        AgentRun(
                            id=str(uuid.uuid4()),
                            task_id=task_id,
                            agent_type="coder",
                            status="running",
                            started_at=now - datetime.timedelta(seconds=9999),
                            finished_at=None,
                        ),
                    ]
                )
                await session.commit()

                est = await estimate_project_size(
                    "app/fleet", db=session, subtask_count=1
                )
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

        # Neither seeded row qualifies -> falls back, not polluted by them.
        assert est.processing_source == "config_fallback"
    finally:
        await _cleanup_task(task_id)
