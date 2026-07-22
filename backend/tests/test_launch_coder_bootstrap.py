"""Gap-closure (Days 11-15 audit, 2026-07-22) — launch_coder() (the "simple"
pipeline mode's coding step) never checked for a blank repo before Day 15's
bootstrap existed at all, and its own bootstrap wiring was missed when Day 15
only wired launch_planning_pipeline() ("full" mode). Confirmed via a real
temp repo that create_worktree() raises RuntimeError against a zero-commit
repo ("invalid reference: HEAD") — exactly the scenario Day 15 exists to
handle, and "simple" mode completely bypassed it.

A second, related bug found while fixing the first: launch_coder()'s outer
`except Exception` handler never transitioned the task to "blocked" (unlike
launch_manager()'s equivalent handler), leaving any task that hit this path
stuck in "coding" status with no valid transition forward via the normal API.

Driven through a real TestClient — launch_coder() uses the shared
get_session_factory() singleton by design (runs inside FastAPI's
BackgroundTasks), so per the documented asyncio shared-engine hazard, a bare
asyncio.run() from sync test code is unsafe here.
"""

from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.bootstrap import BootstrapResult


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _create_ready_task_with_repo(local_path: str) -> tuple[int, int]:
    """A task already at ready_for_review with a plan — as if launch_planner
    already ran — so /approve can drive straight into launch_coder()."""
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask, Repo
    from app.db.repository import create_task

    async def _run() -> tuple[int, int]:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                repo = Repo(
                    github_url="https://github.com/td-owner/td-launch-coder-repo",
                    name="td-launch-coder-repo",
                    local_path=local_path,
                    status="ready",
                )
                session.add(repo)
                await session.commit()
                await session.refresh(repo)

                task = await create_task(
                    session, "launch_coder bootstrap gap test", "desc", repo_id=repo.id
                )
                await session.execute(
                    update(DevTask)
                    .where(DevTask.id == task.id)
                    .values(status="ready_for_review", plan="Do the thing.")
                )
                await session.commit()
                return task.id, repo.id
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


def _get_task_status(task_id: int) -> str:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask

    async def _run() -> str:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                task = await session.get(DevTask, task_id)
                assert task is not None
                return str(task.status)
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


def _cleanup(task_id: int, repo_id: int) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask, Repo

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                await session.execute(delete(Repo).where(Repo.id == repo_id))
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_bootstrap_called_and_task_ends_blocked_not_stuck_when_repo_blank(tmp_path) -> None:
    """The primary gap: blank repo + simple mode used to hard-crash via an
    unhandled create_worktree() RuntimeError with no state recovery. Now:
    bootstrap() is at least attempted, and even when create_worktree() still
    fails afterward (bootstrap mocked here, so the repo is still genuinely
    blank), the task lands in "blocked" — a real, valid, recoverable status —
    instead of stuck forever in "coding"."""
    blank_repo = tmp_path / "blank"
    blank_repo.mkdir()
    task_id, repo_id = _create_ready_task_with_repo(str(blank_repo))
    try:
        with patch(
            "app.pipeline.bootstrap.bootstrap",
            new=AsyncMock(
                return_value=BootstrapResult(bootstrapped=True, project_type="cli")
            ),
        ) as mock_bootstrap:
            with TestClient(app) as client:
                resp = client.post(f"/api/tasks/{task_id}/approve")
            assert resp.status_code == 200, resp.text

        mock_bootstrap.assert_called_once()
        call_args = mock_bootstrap.call_args
        assert call_args.args[0] == task_id
        assert call_args.args[1] == str(blank_repo)

        assert _get_task_status(task_id) == "blocked"
    finally:
        _cleanup(task_id, repo_id)


def test_bootstrap_skipped_when_repo_not_blank(tmp_path) -> None:
    real_repo = tmp_path / "real"
    real_repo.mkdir()
    subprocess.run(["git", "init", str(real_repo)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=real_repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=real_repo, check=True)
    (real_repo / "README.md").write_text("existing project")
    subprocess.run(["git", "add", "."], cwd=real_repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=real_repo, check=True)

    task_id, repo_id = _create_ready_task_with_repo(str(real_repo))
    try:
        with patch("app.pipeline.bootstrap.bootstrap", new=AsyncMock()) as mock_bootstrap, patch(
            "app.api.agents.create_worktree", return_value=real_repo / "worktree"
        ), patch("app.agents.coder.run_coder", return_value=([], None, 10, 10)), patch(
            "app.api.agents.get_diff", return_value=""
        ), patch("app.api.agents.preserve_worktree"):
            with TestClient(app) as client:
                resp = client.post(f"/api/tasks/{task_id}/approve")
            assert resp.status_code == 200, resp.text

        mock_bootstrap.assert_not_called()
        assert _get_task_status(task_id) == "ready_for_review"
    finally:
        _cleanup(task_id, repo_id)
