"""W7 — start from the latest code (2026-10-09).

A GitHub project's folder is a clone; tasks used to start from whatever was
there, possibly days old. Now, before a task starts, the folder is fast-
forwarded to GitHub's latest when that is safe, and left untouched (with a
note in the task log) when it isn't. It never blocks the task.

"GitHub" here is a local bare repository; only the allowed-host check is
relaxed for it.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.git_local_apply import update_from_github


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture(autouse=True)
def _allow_local_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import git_service

    monkeypatch.setattr(git_service, "_validate_remote_url", lambda url: None)


def _github_and_clone(tmp_path: Path) -> tuple[Path, Path, Path]:
    """(bare 'GitHub' repo, a teammate's clone, the user's project folder)."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    mate = tmp_path / "teammate"
    _git(tmp_path, "clone", "-q", str(remote), str(mate))
    (mate / "app.py").write_text("v = 1\n")
    _git(mate, "add", "-A")
    _git(mate, "commit", "-q", "-m", "v1")
    _git(mate, "push", "-q", "origin", "HEAD:main")
    folder = tmp_path / "project"
    _git(tmp_path, "clone", "-q", str(remote), str(folder))
    return remote, mate, folder


def _new_commit_on_github(mate: Path, text: str = "v = 2\n") -> None:
    (mate / "app.py").write_text(text)
    _git(mate, "commit", "-q", "-am", "newer")
    _git(mate, "push", "-q", "origin", "HEAD:main")


def _update(folder: Path) -> Any:
    return asyncio.run(update_from_github(str(folder), None))


def test_an_old_copy_is_brought_up_to_date(tmp_path: Path) -> None:
    _, mate, folder = _github_and_clone(tmp_path)
    _new_commit_on_github(mate)
    r = _update(folder)
    assert r.applied and "1 new commits" in r.message
    assert (folder / "app.py").read_text() == "v = 2\n"


def test_an_up_to_date_copy_is_left_alone(tmp_path: Path) -> None:
    _, _, folder = _github_and_clone(tmp_path)
    r = _update(folder)
    assert not r.applied and "Already up to date" in r.message


def test_unsaved_edits_are_never_overwritten(tmp_path: Path) -> None:
    _, mate, folder = _github_and_clone(tmp_path)
    _new_commit_on_github(mate)
    (folder / "app.py").write_text("v = 'mine'\n")
    r = _update(folder)
    assert not r.applied and "unsaved changes" in r.message
    assert (folder / "app.py").read_text() == "v = 'mine'\n"


def test_a_copy_with_its_own_commits_is_left_alone(tmp_path: Path) -> None:
    _, mate, folder = _github_and_clone(tmp_path)
    _new_commit_on_github(mate)
    (folder / "local.py").write_text("x = 1\n")
    _git(folder, "add", "-A")
    _git(folder, "commit", "-q", "-m", "my own work")
    head = _git(folder, "rev-parse", "HEAD")
    r = _update(folder)
    assert not r.applied and "its own commits" in r.message
    assert _git(folder, "rev-parse", "HEAD") == head


def test_github_unreachable_never_blocks(tmp_path: Path) -> None:
    remote, _, folder = _github_and_clone(tmp_path)
    subprocess.run(["rm", "-rf", str(remote)], check=True)
    r = _update(folder)
    assert not r.applied and "Could not reach GitHub" in r.message


def test_repository_hooks_never_run(tmp_path: Path) -> None:
    _, mate, folder = _github_and_clone(tmp_path)
    _new_commit_on_github(mate)
    marker = tmp_path / "hook-ran"
    hook = folder / ".git" / "hooks" / "post-merge"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    assert _update(folder).applied
    assert not marker.exists()


# -- wiring: POST /api/tasks/{id}/run -----------------------------------------


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


def test_starting_a_task_updates_the_folder_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import delete, select, update

    from app.api import tasks
    from app.db.models import DevTask, Project, Repo, TaskLog
    from app.db.repository import create_task

    async def no_launch(*a: Any, **k: Any) -> None:
        return None

    monkeypatch.setattr(tasks, "dispatch_job", no_launch)
    _, mate, folder = _github_and_clone(tmp_path)
    _new_commit_on_github(mate)

    async def make(s):  # type: ignore[no-untyped-def]
        repo = Repo(
            name="w7",
            github_url="https://github.com/w7-owner/w7",
            local_path=str(folder),
            status="ready",
        )
        s.add(repo)
        await s.commit()
        await s.refresh(repo)
        project = Project(name="W7", repo_id=repo.id, source="github_existing")
        s.add(project)
        await s.commit()
        await s.refresh(project)
        task = await create_task(s, "w7 task", "desc")
        await s.execute(
            update(DevTask)
            .where(DevTask.id == task.id)
            .values(repo_id=repo.id, project_id=project.id)
        )
        await s.commit()
        return task.id, project.id, repo.id

    task_id, project_id, repo_id = _db(make)
    try:
        with TestClient(app) as client:
            r = client.post(f"/api/tasks/{task_id}/run", json={})
            assert r.status_code == 200 and r.json()["triggered"] is True
        assert (folder / "app.py").read_text() == "v = 2\n"

        async def logs(s):  # type: ignore[no-untyped-def]
            rows = await s.execute(
                select(TaskLog.message).where(TaskLog.task_id == task_id)
            )
            return [m for (m,) in rows]

        assert any("Updated to the latest code from GitHub" in m for m in _db(logs))
    finally:

        async def clean(s):  # type: ignore[no-untyped-def]
            await s.execute(delete(TaskLog).where(TaskLog.task_id == task_id))
            await s.execute(delete(DevTask).where(DevTask.id == task_id))
            await s.execute(delete(Project).where(Project.id == project_id))
            await s.execute(delete(Repo).where(Repo.id == repo_id))
            await s.commit()

        _db(clean)
