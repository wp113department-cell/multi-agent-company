"""Production audit 2026-09-29 — simple mode (launch_planner -> launch_coder)
vs full mode parity.

Found: (1) the task's attached images were never fetched or passed in simple
mode (full mode's pm/architect/frontend_dev/reviewer always get them); (2)
simple mode never recorded the git-push approval — which is also what sets
DevTask.branch_name, so POST /api/tasks/{id}/push refused every simple-mode
task ("Task has no branch to push") and it could never become a PR.

Real git repo, real worktree, real DB; only the LLM-driven run_coder is
replaced (it writes a real file into the real worktree).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import reset_settings_cache
from app.db.models import DevTask, PendingApproval, Repo
from app.db.repository import create_task_image
from tests.test_audit04_orchestration_fixes import (
    _cleanup_task,
    _create_task_with_status,
    _new_isolated_db_engine,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=a", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("WORKTREES_DIR", str(tmp_path / "wts"))
    # the real workspace guard (ALLOWED_WORKSPACE_PARENT) rejects /tmp paths
    monkeypatch.setenv("ALLOWED_WORKSPACE_PARENT", str(tmp_path))
    reset_settings_cache()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("print('hi')\n")
    _git(repo_dir, "init", "-q")
    _git(repo_dir, "add", ".")
    _git(repo_dir, "commit", "-qm", "init")

    async def _setup() -> int:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:  # type: ignore[arg-type]
                repo = Repo(
                    name=f"audit-parity-{tmp_path.name}",
                    local_path=str(repo_dir),
                    github_url="https://github.com/audit-owner/audit-parity",
                )
                s.add(repo)
                await s.commit()
                return int(repo.id)
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    repo_id = asyncio.run(_setup())
    task_id = _create_task_with_status("coding", repo_id=repo_id)
    yield task_id, repo_dir
    _cleanup_task(task_id, repo_id)
    reset_settings_cache()


def test_launch_coder_forwards_images_and_records_push_approval(world) -> None:  # type: ignore[no-untyped-def]
    task_id, repo_dir = world
    seen: dict[str, Any] = {}

    def fake_run_coder(**kwargs: Any) -> tuple[list[str], None, int, int]:
        seen.update(kwargs)
        (Path(kwargs["worktree_path"]) / "feature.py").write_text("x = 1\n")
        return ["feature.py"], None, 1, 1

    async def _go() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine)() as s:  # type: ignore[arg-type]
                await create_task_image(s, task_id, "iVBORw0KGgo=", "image/png")
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

        from app.api.agents import launch_coder

        with patch("app.agents.coder.run_coder", side_effect=fake_run_coder):
            await launch_coder(task_id, "the plan", str(repo_dir))

    asyncio.run(_go())

    # (1) images reached the coder
    assert seen["images"] == [{"media_type": "image/png", "data": "iVBORw0KGgo="}]

    async def _read() -> tuple[DevTask, PendingApproval | None]:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine)() as s:  # type: ignore[arg-type]
                task = (
                    await s.execute(select(DevTask).where(DevTask.id == task_id))
                ).scalar_one()
                appr = (
                    await s.execute(
                        select(PendingApproval).where(
                            PendingApproval.thread_id == f"task-{task_id}-push"
                        )
                    )
                ).scalar_one_or_none()
                return task, appr
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    task, approval = asyncio.run(_read())
    # (2) push approval recorded, branch known, PR state pending
    assert task.status == "ready_for_review"
    assert task.branch_name == f"agent/task-{task_id}"
    assert task.pr_status == "pending"
    assert approval is not None and approval.status == "pending"
    assert approval.action == "git_push"
