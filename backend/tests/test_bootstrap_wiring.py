"""Day 15 — bootstrap() wiring into launch_planning_pipeline().

bootstrap()'s own orchestration is covered in test_bootstrap.py. This file
is about the ONE integration point: launch_planning_pipeline() must call
bootstrap() when (and only when) the task's repo is blank, before handing
off to the normal PM->Architect->Decomposer pipeline.

launch_planning_pipeline() uses app.db.session.get_session_factory() (the
shared, process-wide engine) — by design, since it runs inside FastAPI's
BackgroundTasks on the app's own already-running event loop. Per the
documented asyncio shared-engine hazard (Day 14), driven entirely through a
real TestClient here (one continuous event loop for the whole test), not a
bare asyncio.run().
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


def _create_task_with_repo(local_path: str) -> tuple[int, int]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import Repo
    from app.db.repository import create_task

    async def _run() -> tuple[int, int]:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                repo = Repo(
                    github_url="https://github.com/td-owner/td-bootstrap-repo",
                    name="td-bootstrap-repo",
                    local_path=local_path,
                    status="ready",
                )
                session.add(repo)
                await session.commit()
                await session.refresh(repo)

                task = await create_task(
                    session, "bootstrap wiring test", "desc", repo_id=repo.id
                )
                return task.id, repo.id
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


def _cleanup(task_id: int, repo_id: int) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask, PendingApproval, Repo

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(
                    delete(PendingApproval).where(PendingApproval.task_id == task_id)
                )
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                await session.execute(delete(Repo).where(Repo.id == repo_id))
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_bootstrap_called_when_repo_is_blank(tmp_path) -> None:
    blank_repo = tmp_path / "blank"
    blank_repo.mkdir()
    task_id, repo_id = _create_task_with_repo(str(blank_repo))
    try:
        with patch(
            "app.pipeline.bootstrap.bootstrap",
            new=AsyncMock(return_value=BootstrapResult(bootstrapped=True, project_type="cli", files_created=["main.py"], commit_sha="deadbeef")),
        ) as mock_bootstrap, patch(
            "app.pipeline.graph.run_planning_pipeline",
            new=AsyncMock(return_value={"stage": "blocked", "error": "test short-circuit"}),
        ):
            with TestClient(app) as client:
                resp = client.post(f"/api/tasks/{task_id}/run", json={"mode": "full"})
            assert resp.status_code == 200, resp.text

        mock_bootstrap.assert_called_once()
        call_args = mock_bootstrap.call_args
        assert call_args.args[0] == task_id
        assert call_args.args[1] == str(blank_repo)
    finally:
        _cleanup(task_id, repo_id)


def test_bootstrap_skipped_when_repo_not_blank(tmp_path) -> None:
    real_repo = tmp_path / "real"
    real_repo.mkdir()
    subprocess.run(["git", "init", str(real_repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=real_repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=real_repo, check=True)
    (real_repo / "README.md").write_text("existing project")
    subprocess.run(["git", "add", "."], cwd=real_repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=real_repo, check=True)

    task_id, repo_id = _create_task_with_repo(str(real_repo))
    try:
        with patch(
            "app.pipeline.bootstrap.bootstrap", new=AsyncMock()
        ) as mock_bootstrap, patch(
            "app.pipeline.graph.run_planning_pipeline",
            new=AsyncMock(return_value={"stage": "blocked", "error": "test short-circuit"}),
        ):
            with TestClient(app) as client:
                resp = client.post(f"/api/tasks/{task_id}/run", json={"mode": "full"})
            assert resp.status_code == 200, resp.text

        mock_bootstrap.assert_not_called()
    finally:
        _cleanup(task_id, repo_id)
