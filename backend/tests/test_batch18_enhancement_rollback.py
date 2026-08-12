"""AUDIT_Q_BATCH18 §69 gap-closure (2026-08-12) — "Autonomous Quality
Improvement" step 8 ("rollback if quality declines") was real and fully
automatic for PROMPT versions (_prompt_auto_rollback_loop) but missing for
EnhancementRequest-driven CODE commits. Tests app.fleet.enhancement_rollback
against a real DB (isolated engine, never the shared app.db.session
singleton — same rationale test_day9_fleet_agents.py's own
_with_isolated_session documents) and a real temp git repo.

Every test does its DB work (seed, exercise, cleanup) inside ONE async
function invoked via a single asyncio.run() call — a fresh engine created
and disposed within that same call. Splitting engine creation from usage
across multiple asyncio.run() calls binds the engine's connection pool to
whichever event loop touched it first, which breaks on the second call
(see feedback_verify_real_callers / the asyncio-isolated-engine rule this
codebase's own test files already document, e.g. test_day9_fleet_agents.py's
_with_isolated_session docstring).
"""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.fleet.enhancement_rollback import (
    capture_commit_sha_if_verified,
    check_and_handle_quality_decline,
    compute_success_rate_window,
    evaluate_quality_decline,
)


@pytest.fixture(autouse=True)
def _reset_settings():
    from app.config import reset_settings_cache

    reset_settings_cache()  # noqa: E702
    yield
    reset_settings_cache()  # noqa: E702


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _seed_task_and_runs(
    session: Any, agent_type: str, runs: list[tuple[str, datetime]]
) -> int:
    """Creates one real DevTask + N real AgentRun rows (status, started_at)
    for agent_type, using an already-open session. Returns the DevTask id."""
    from app.db.models import AgentRun
    from app.db.repository import create_task

    task = await create_task(session, "batch18 rollback test task", "desc")
    for status, started_at in runs:
        session.add(
            AgentRun(
                id=str(uuid.uuid4()),
                task_id=task.id,
                agent_type=agent_type,
                status=status,
                started_at=started_at,
            )
        )
    await session.commit()
    return int(task.id)


async def _cleanup_task(session: Any, task_id: int) -> None:
    from sqlalchemy import delete

    from app.db.models import AgentRun, DevTask

    await session.execute(delete(AgentRun).where(AgentRun.task_id == task_id))
    await session.execute(delete(DevTask).where(DevTask.id == task_id))
    await session.commit()


class TestComputeSuccessRateWindow:
    def test_computes_real_rate_from_window(self) -> None:
        agent_type = f"batch18_rate_{uuid.uuid4().hex[:8]}"
        base = datetime.now(timezone.utc) - timedelta(days=10)

        async def _do() -> None:
            from sqlalchemy.ext.asyncio import create_async_engine

            from app.config import get_settings

            engine = create_async_engine(
                get_settings().database_url, pool_pre_ping=True
            )
            try:
                from sqlalchemy.ext.asyncio import async_sessionmaker

                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    task_id = await _seed_task_and_runs(
                        session,
                        agent_type,
                        [
                            ("completed", base),
                            ("completed", base + timedelta(minutes=1)),
                            ("completed", base + timedelta(minutes=2)),
                            ("failed", base + timedelta(minutes=3)),
                        ],
                    )
                    try:
                        rate, count = await compute_success_rate_window(
                            session,
                            agent_type,
                            base - timedelta(minutes=1),
                            base + timedelta(minutes=10),
                        )
                        assert count == 4
                        assert rate == pytest.approx(0.75)
                    finally:
                        await _cleanup_task(session, task_id)
            finally:
                await engine.dispose()

        _run(_do())

    def test_no_runs_in_window_returns_none(self) -> None:
        agent_type = f"batch18_empty_{uuid.uuid4().hex[:8]}"

        async def _do() -> None:
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            from app.config import get_settings

            engine = create_async_engine(
                get_settings().database_url, pool_pre_ping=True
            )
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    rate, count = await compute_success_rate_window(
                        session,
                        agent_type,
                        datetime.now(timezone.utc) - timedelta(days=1),
                        datetime.now(timezone.utc),
                    )
                    assert rate is None
                    assert count == 0
            finally:
                await engine.dispose()

        _run(_do())


def _decline_kwargs(**overrides: Any) -> dict[str, Any]:
    base = dict(
        pre_window_hours=168.0,
        min_post_window_hours=0.0,
        min_runs=3,
        decline_threshold=0.15,
    )
    base.update(overrides)
    return base


class TestEvaluateQualityDecline:
    def test_real_decline_is_detected(self) -> None:
        agent_type = f"batch18_decline_{uuid.uuid4().hex[:8]}"
        completed_at = datetime.now(timezone.utc) - timedelta(hours=5)
        pre_start = completed_at - timedelta(hours=1)

        async def _do() -> None:
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            from app.config import get_settings

            engine = create_async_engine(
                get_settings().database_url, pool_pre_ping=True
            )
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    task_id = await _seed_task_and_runs(
                        session,
                        agent_type,
                        [
                            # pre-window: 4/4 completed = 100%
                            ("completed", pre_start),
                            ("completed", pre_start + timedelta(minutes=1)),
                            ("completed", pre_start + timedelta(minutes=2)),
                            ("completed", pre_start + timedelta(minutes=3)),
                            # post-window: 1/4 completed = 25%
                            ("failed", completed_at + timedelta(minutes=1)),
                            ("failed", completed_at + timedelta(minutes=2)),
                            ("failed", completed_at + timedelta(minutes=3)),
                            ("completed", completed_at + timedelta(minutes=4)),
                        ],
                    )
                    try:
                        request = SimpleNamespace(
                            id=999, agent_name=agent_type, completed_at=completed_at
                        )
                        report = await evaluate_quality_decline(
                            session, request, **_decline_kwargs()
                        )
                        assert report is not None
                        assert report.declined is True
                        assert report.pre_success_rate == pytest.approx(1.0)
                        assert report.post_success_rate == pytest.approx(0.25)
                    finally:
                        await _cleanup_task(session, task_id)
            finally:
                await engine.dispose()

        _run(_do())

    def test_stable_agent_is_not_declined(self) -> None:
        agent_type = f"batch18_stable_{uuid.uuid4().hex[:8]}"
        completed_at = datetime.now(timezone.utc) - timedelta(hours=5)
        pre_start = completed_at - timedelta(hours=1)

        async def _do() -> None:
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            from app.config import get_settings

            engine = create_async_engine(
                get_settings().database_url, pool_pre_ping=True
            )
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    task_id = await _seed_task_and_runs(
                        session,
                        agent_type,
                        [
                            ("completed", pre_start),
                            ("completed", pre_start + timedelta(minutes=1)),
                            ("failed", pre_start + timedelta(minutes=2)),
                            ("completed", completed_at + timedelta(minutes=1)),
                            ("completed", completed_at + timedelta(minutes=2)),
                            ("failed", completed_at + timedelta(minutes=3)),
                        ],
                    )
                    try:
                        request = SimpleNamespace(
                            id=998, agent_name=agent_type, completed_at=completed_at
                        )
                        report = await evaluate_quality_decline(
                            session, request, **_decline_kwargs()
                        )
                        assert report is not None
                        assert report.declined is False
                    finally:
                        await _cleanup_task(session, task_id)
            finally:
                await engine.dispose()

        _run(_do())

    def test_insufficient_runs_returns_none(self) -> None:
        agent_type = f"batch18_thin_{uuid.uuid4().hex[:8]}"
        completed_at = datetime.now(timezone.utc) - timedelta(hours=5)

        async def _do() -> None:
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            from app.config import get_settings

            engine = create_async_engine(
                get_settings().database_url, pool_pre_ping=True
            )
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    task_id = await _seed_task_and_runs(
                        session,
                        agent_type,
                        [("completed", completed_at + timedelta(minutes=1))],
                    )
                    try:
                        request = SimpleNamespace(
                            id=997, agent_name=agent_type, completed_at=completed_at
                        )
                        report = await evaluate_quality_decline(
                            session, request, **_decline_kwargs()
                        )
                        assert report is None
                    finally:
                        await _cleanup_task(session, task_id)
            finally:
                await engine.dispose()

        _run(_do())

    def test_min_post_window_not_yet_elapsed_returns_none(self) -> None:
        request = SimpleNamespace(
            id=996,
            agent_name="whatever",
            completed_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )

        async def _do() -> None:
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            from app.config import get_settings

            engine = create_async_engine(
                get_settings().database_url, pool_pre_ping=True
            )
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    report = await evaluate_quality_decline(
                        session, request, **_decline_kwargs(min_post_window_hours=48.0)
                    )
                    assert report is None
            finally:
                await engine.dispose()

        _run(_do())

    def test_no_completed_at_returns_none(self) -> None:
        request = SimpleNamespace(id=995, agent_name="whatever", completed_at=None)

        async def _do() -> None:
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            from app.config import get_settings

            engine = create_async_engine(
                get_settings().database_url, pool_pre_ping=True
            )
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    report = await evaluate_quality_decline(
                        session, request, **_decline_kwargs()
                    )
                    assert report is None
            finally:
                await engine.dispose()

        _run(_do())


class TestCaptureCommitShaIfVerified:
    def test_captures_head_when_committed_flag_true(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@example.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "T"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        (Path(tmp_path) / "f.txt").write_text("x")
        subprocess.run(
            ["git", "add", "f.txt"], cwd=tmp_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "c"], cwd=tmp_path, check=True, capture_output=True
        )
        expected = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        sha = capture_commit_sha_if_verified(
            str(tmp_path), {"verification": {"committed": True}}
        )
        assert sha == expected

    def test_returns_none_when_not_committed(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        sha = capture_commit_sha_if_verified(
            str(tmp_path), {"verification": {"committed": False}}
        )
        assert sha is None


class TestCheckAndHandleQualityDecline:
    def test_declined_request_is_reverted(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
        from app.config import reset_settings_cache

        reset_settings_cache()  # noqa: E702

        # Real repo with a commit to revert.
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@example.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "T"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        f = Path(tmp_path) / "f.txt"
        f.write_text("original\n")
        subprocess.run(
            ["git", "add", "f.txt"], cwd=tmp_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        f.write_text("bad enhancement\n")
        subprocess.run(
            ["git", "add", "f.txt"], cwd=tmp_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "enhancement"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        bad_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        agent_type = f"batch18_e2e_{uuid.uuid4().hex[:8]}"
        completed_at = datetime.now(timezone.utc) - timedelta(hours=5)
        pre_start = completed_at - timedelta(hours=1)

        async def _do() -> None:
            from sqlalchemy import delete, select
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            from app.config import get_settings
            from app.db.models import EnhancementRequest

            engine = create_async_engine(
                get_settings().database_url, pool_pre_ping=True
            )
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    task_id = await _seed_task_and_runs(
                        session,
                        agent_type,
                        [
                            ("completed", pre_start),
                            ("completed", pre_start + timedelta(minutes=1)),
                            ("completed", pre_start + timedelta(minutes=2)),
                            ("failed", completed_at + timedelta(minutes=1)),
                            ("failed", completed_at + timedelta(minutes=2)),
                            ("failed", completed_at + timedelta(minutes=3)),
                        ],
                    )
                    row = EnhancementRequest(
                        agent_name=agent_type,
                        title="t",
                        description="d",
                        category="bug",
                        priority="low",
                        status="completed",
                        commit_sha=bad_sha,
                        completed_at=completed_at,
                        quality_check_status="monitoring",
                    )
                    session.add(row)
                    await session.commit()
                    await session.refresh(row)
                    request_id = row.id
                    try:
                        outcome = await check_and_handle_quality_decline(
                            session,
                            row,
                            repo_path=str(tmp_path),
                            pre_window_hours=168.0,
                            min_post_window_hours=0.0,
                            min_runs=2,
                            decline_threshold=0.15,
                        )
                        assert outcome["action"] == "rolled_back"
                        assert f.read_text() == "original\n"

                        r = await session.execute(
                            select(EnhancementRequest).where(
                                EnhancementRequest.id == request_id
                            )
                        )
                        fresh = r.scalar_one()
                        assert fresh.quality_check_status == "rolled_back"
                        assert fresh.rollback_commit_sha
                        assert fresh.rollback_at is not None
                    finally:
                        await session.execute(
                            delete(EnhancementRequest).where(
                                EnhancementRequest.id == request_id
                            )
                        )
                        await session.commit()
                        await _cleanup_task(session, task_id)
            finally:
                await engine.dispose()

        _run(_do())

    def test_stable_request_is_marked_stable_not_reverted(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        agent_type = f"batch18_e2e_stable_{uuid.uuid4().hex[:8]}"
        completed_at = datetime.now(timezone.utc) - timedelta(hours=5)
        pre_start = completed_at - timedelta(hours=1)

        async def _do() -> None:
            from sqlalchemy import delete
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            from app.config import get_settings
            from app.db.models import EnhancementRequest

            engine = create_async_engine(
                get_settings().database_url, pool_pre_ping=True
            )
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    task_id = await _seed_task_and_runs(
                        session,
                        agent_type,
                        [
                            ("completed", pre_start),
                            ("completed", pre_start + timedelta(minutes=1)),
                            ("completed", completed_at + timedelta(minutes=1)),
                            ("completed", completed_at + timedelta(minutes=2)),
                        ],
                    )
                    row = EnhancementRequest(
                        agent_name=agent_type,
                        title="t",
                        description="d",
                        category="bug",
                        priority="low",
                        status="completed",
                        commit_sha="deadbeef",
                        completed_at=completed_at,
                        quality_check_status="monitoring",
                    )
                    session.add(row)
                    await session.commit()
                    await session.refresh(row)
                    request_id = row.id
                    try:
                        outcome = await check_and_handle_quality_decline(
                            session,
                            row,
                            repo_path=str(tmp_path),
                            pre_window_hours=168.0,
                            min_post_window_hours=0.0,
                            min_runs=2,
                            decline_threshold=0.15,
                        )
                        assert outcome["action"] == "stable"
                        assert row.quality_check_status == "stable"
                    finally:
                        await session.execute(
                            delete(EnhancementRequest).where(
                                EnhancementRequest.id == request_id
                            )
                        )
                        await session.commit()
                        await _cleanup_task(session, task_id)
            finally:
                await engine.dispose()

        _run(_do())
