"""W6 — deliver to the right branch (2026-10-09).

A pull request always targeted `main`, so a repository whose default branch
is `master` (or anything else) failed at the very last step. Now the base is
the project's own choice, else the repository's default branch.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.git_push_tool import PushResult, resolve_target_branch


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _clone_of(tmp_path: Path, default_branch: str) -> Path:
    """A clone of a remote whose default branch is `default_branch`."""
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q", "-b", default_branch)
    (src / "a.txt").write_text("a\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "a")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(src), str(clone))
    return clone


def _resolve(target: str | None, path: Path) -> str:
    return asyncio.run(resolve_target_branch(target, str(path)))


def test_a_master_repository_gets_its_pr_into_master(tmp_path: Path) -> None:
    assert _resolve(None, _clone_of(tmp_path, "master")) == "master"


def test_any_default_branch_name_is_used(tmp_path: Path) -> None:
    assert _resolve(None, _clone_of(tmp_path, "develop")) == "develop"


def test_without_origin_head_an_existing_master_is_used(tmp_path: Path) -> None:
    clone = _clone_of(tmp_path, "master")
    _git(clone, "remote", "set-head", "origin", "--delete")
    assert _resolve(None, clone) == "master"


def test_the_projects_own_choice_wins(tmp_path: Path) -> None:
    assert _resolve("release/2.0", _clone_of(tmp_path, "master")) == "release/2.0"


def test_an_invalid_choice_is_ignored(tmp_path: Path) -> None:
    assert _resolve("bad..name", _clone_of(tmp_path, "master")) == "master"


def test_main_is_only_the_last_resort(tmp_path: Path) -> None:
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    _git(lonely, "init", "-q")
    assert _resolve(None, lonely) == "main"


# -- wiring -------------------------------------------------------------------


def _db(fn):  # type: ignore[no-untyped-def]
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings

    async def _run():  # type: ignore[no-untyped-def]
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                return await fn(s)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


@pytest.fixture
def github_task(tmp_path: Path):  # type: ignore[no-untyped-def]
    from sqlalchemy import delete, update

    from app.db.models import DevTask, PendingApproval, Project, Repo
    from app.db.repository import create_task

    clone = _clone_of(tmp_path, "master")

    async def make(s):  # type: ignore[no-untyped-def]
        repo = Repo(
            name="w6",
            github_url="https://github.com/w6-owner/w6-repo",
            local_path=str(clone),
            status="ready",
        )
        s.add(repo)
        await s.commit()
        await s.refresh(repo)
        project = Project(name="W6 project", repo_id=repo.id, source="github_existing")
        s.add(project)
        await s.commit()
        await s.refresh(project)
        task = await create_task(s, "w6 task", "desc")
        await s.execute(
            update(DevTask)
            .where(DevTask.id == task.id)
            .values(
                repo_id=repo.id,
                project_id=project.id,
                branch_name=f"agent/task-{task.id}",
            )
        )
        await s.commit()
        return task.id, project.id, repo.id

    task_id, project_id, repo_id = _db(make)
    yield task_id, project_id

    async def cleanup(s):  # type: ignore[no-untyped-def]
        await s.execute(
            delete(PendingApproval).where(PendingApproval.task_id == task_id)
        )
        await s.execute(delete(DevTask).where(DevTask.id == task_id))
        await s.execute(delete(Project).where(Project.id == project_id))
        await s.execute(delete(Repo).where(Repo.id == repo_id))
        await s.commit()

    _db(cleanup)


def _push(task_id: int) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    async def fake_push(**kwargs: Any) -> PushResult:
        seen.update(kwargs)
        return PushResult(
            pushed=True, pr_url="https://github.com/x/y/pull/1", pr_number=1
        )

    with patch("app.tools.git_push_tool.push_and_create_pr", side_effect=fake_push):
        with TestClient(app) as client:
            assert client.post(f"/api/tasks/{task_id}/push").status_code == 200
    return seen


def test_delivery_targets_the_repositorys_default_branch(github_task) -> None:  # type: ignore[no-untyped-def]
    task_id, _ = github_task
    assert _push(task_id)["base_branch"] == "master"


def test_delivery_targets_the_projects_chosen_branch(github_task) -> None:  # type: ignore[no-untyped-def]
    task_id, project_id = github_task
    with TestClient(app) as client:
        r = client.patch(
            f"/api/projects/{project_id}", json={"target_branch": "release/2.0"}
        )
        assert r.status_code == 200 and r.json()["targetBranch"] == "release/2.0"
    assert _push(task_id)["base_branch"] == "release/2.0"


def test_project_branch_setting_is_validated_and_can_be_cleared(github_task) -> None:  # type: ignore[no-untyped-def]
    _, project_id = github_task
    with TestClient(app) as client:
        bad = client.patch(
            f"/api/projects/{project_id}", json={"target_branch": "a..b"}
        )
        assert bad.status_code == 400
        client.patch(f"/api/projects/{project_id}", json={"target_branch": "develop"})
        cleared = client.patch(
            f"/api/projects/{project_id}", json={"target_branch": ""}
        )
        assert cleared.json()["targetBranch"] is None
        renamed = client.patch(f"/api/projects/{project_id}", json={"name": "Renamed"})
        assert renamed.json()["targetBranch"] is None  # untouched by other edits


def test_a_missing_folder_never_breaks_delivery(tmp_path: Path) -> None:
    assert _resolve(None, tmp_path / "gone") == "main"
