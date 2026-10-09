"""W2 — "Apply to my folder" (2026-10-09).

A project that lives only on this computer (no GitHub link) used to end every
task with its work stuck on the `agent/task-{id}` branch: no delivery
decision was ever created, and approving delivery set pr_status="failed".
Now the delivery decision is created for such projects too, and approving
it merges the branch into the folder's current branch — never overwriting
the user's own uncommitted or conflicting work.

The merge tests use real git repositories in tmp_path; the dispatch tests
use the real DB through the API, like test_git_push_approval_dispatch.py.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.fleet import approval_gate as ag
from app.main import app
from app.tools.git_local_apply import apply_task_branch

TASK = 4242


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _project_with_finished_task(tmp_path: Path, task_id: int = TASK) -> Path:
    """A user's folder (branch main) plus a task worktree whose branch
    agent/task-{id} has one committed change, the way the pipeline leaves it."""
    folder = tmp_path / "my-project"
    folder.mkdir()
    _git(folder, "init", "-q", "-b", "main")
    (folder / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    _git(folder, "add", "-A")
    _git(folder, "commit", "-q", "-m", "start")
    wt = tmp_path / "worktree"
    _git(folder, "worktree", "add", "-q", "-b", f"agent/task-{task_id}", str(wt))
    (wt / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef subtract(a, b):\n    return a - b\n"
    )
    _git(wt, "commit", "-q", "-am", "add subtract")
    return folder


def _apply(folder: Path, task_id: int = TASK):  # type: ignore[no-untyped-def]
    return asyncio.run(apply_task_branch(task_id, str(folder), "Add subtract"))


# -- the merge itself --------------------------------------------------------


def test_finished_work_lands_in_the_users_folder(tmp_path: Path) -> None:
    folder = _project_with_finished_task(tmp_path)
    result = _apply(folder)
    assert result.applied, result.message
    assert "subtract" in (folder / "calc.py").read_text()
    assert _git(folder, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert (
        _git(folder, "log", "-1", "--format=%s") == f"Apply task #{TASK}: Add subtract"
    )
    assert result.commit == _git(folder, "rev-parse", "HEAD")


def test_applying_twice_is_harmless(tmp_path: Path) -> None:
    folder = _project_with_finished_task(tmp_path)
    assert _apply(folder).applied
    head = _git(folder, "rev-parse", "HEAD")
    again = _apply(folder)
    assert again.applied and "Already" in again.message
    assert _git(folder, "rev-parse", "HEAD") == head


def test_uncommitted_user_changes_are_never_touched(tmp_path: Path) -> None:
    folder = _project_with_finished_task(tmp_path)
    (folder / "calc.py").write_text("# my unsaved edit\n")
    head = _git(folder, "rev-parse", "HEAD")
    result = _apply(folder)
    assert not result.applied
    assert "calc.py" in result.message and "Nothing was changed" in result.message
    assert (folder / "calc.py").read_text() == "# my unsaved edit\n"
    assert _git(folder, "rev-parse", "HEAD") == head


def test_a_conflict_is_undone_and_explained(tmp_path: Path) -> None:
    folder = _project_with_finished_task(tmp_path)
    (folder / "calc.py").write_text("def add(a, b):\n    return b + a  # mine\n")
    _git(folder, "commit", "-q", "-am", "my own newer change")
    head = _git(folder, "rev-parse", "HEAD")
    result = _apply(folder)
    assert not result.applied
    assert "calc.py" in result.message and "left exactly as it was" in result.message
    assert _git(folder, "rev-parse", "HEAD") == head
    assert not (folder / ".git" / "MERGE_HEAD").exists()
    assert _git(folder, "status", "--porcelain", "--untracked-files=no") == ""


def test_a_detached_folder_is_refused(tmp_path: Path) -> None:
    folder = _project_with_finished_task(tmp_path)
    _git(folder, "checkout", "-q", "--detach")
    result = _apply(folder)
    assert not result.applied and "not on a branch" in result.message


def test_missing_branch_is_refused(tmp_path: Path) -> None:
    folder = _project_with_finished_task(tmp_path)
    result = _apply(folder, task_id=999999)
    assert not result.applied and "no finished work" in result.message


def test_repository_hooks_never_run_in_the_backend(tmp_path: Path) -> None:
    folder = _project_with_finished_task(tmp_path)
    marker = tmp_path / "hook-ran"
    hook = folder / ".git" / "hooks" / "post-merge"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    assert _apply(folder).applied
    assert not marker.exists()


# -- wiring: decision created, approval applies -----------------------------


def _engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _db(fn):  # type: ignore[no-untyped-def]
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async def _run():  # type: ignore[no-untyped-def]
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:  # type: ignore[arg-type]
                return await fn(s)
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


@pytest.fixture
def local_task(tmp_path: Path):  # type: ignore[no-untyped-def]
    """A task of a local-only project (repo row with a folder, no GitHub)."""
    from sqlalchemy import delete, update

    from app.db.models import DevTask, PendingApproval, Repo
    from app.db.repository import create_task

    async def make(s):  # type: ignore[no-untyped-def]
        task = await create_task(s, "Add subtract", "desc")
        return task.id

    task_id = _db(make)
    folder = _project_with_finished_task(tmp_path, task_id)

    async def link(s):  # type: ignore[no-untyped-def]
        repo = Repo(name="my-project", local_path=str(folder), status="ready")
        s.add(repo)
        await s.commit()
        await s.refresh(repo)
        await s.execute(
            update(DevTask)
            .where(DevTask.id == task_id)
            .values(
                repo_id=repo.id,
                branch_name=f"agent/task-{task_id}",
                status="ready_for_review",
            )
        )
        await s.commit()
        return repo.id

    repo_id = _db(link)
    yield task_id, folder

    async def cleanup(s):  # type: ignore[no-untyped-def]
        await s.execute(
            delete(PendingApproval).where(PendingApproval.task_id == task_id)
        )
        await s.execute(delete(DevTask).where(DevTask.id == task_id))
        await s.execute(delete(Repo).where(Repo.id == repo_id))
        await s.commit()

    _db(cleanup)


def _task(task_id: int):  # type: ignore[no-untyped-def]
    from app.db.models import DevTask

    async def get(s):  # type: ignore[no-untyped-def]
        return await s.get(DevTask, task_id)

    return _db(get)


def test_a_local_project_gets_the_delivery_decision(local_task) -> None:  # type: ignore[no-untyped-def]
    from app.api.agents import _record_git_push_approval

    task_id, folder = local_task

    async def record(s):  # type: ignore[no-untyped-def]
        await _record_git_push_approval(s, task_id, str(folder), ["calc.py"], "diff", 1)

    _db(record)
    approval = ag.get_pending(f"task-{task_id}-push")
    assert approval is not None and approval.action == "git_push"
    assert approval.details["delivery"] == "folder"
    assert approval.details["folder"] == str(folder)
    assert _task(task_id).pr_status == "pending"


def test_approving_delivery_applies_and_completes(local_task) -> None:  # type: ignore[no-untyped-def]
    task_id, folder = local_task
    with TestClient(app) as client:
        assert client.post(f"/api/tasks/{task_id}/push").status_code == 200
        pr = client.get(f"/api/tasks/{task_id}/pr").json()
    assert "subtract" in (folder / "calc.py").read_text()
    task = _task(task_id)
    assert task.pr_status == "applied"
    assert task.status == "completed"
    assert pr["delivery"] == "folder" and pr["prStatus"] == "applied"


def test_a_refused_apply_can_be_retried(local_task) -> None:  # type: ignore[no-untyped-def]
    task_id, folder = local_task
    (folder / "calc.py").write_text("# unsaved\n")
    with TestClient(app) as client:
        client.post(f"/api/tasks/{task_id}/push")
        assert _task(task_id).pr_status == "failed"
        assert (folder / "calc.py").read_text() == "# unsaved\n"
        _git(folder, "checkout", "--", "calc.py")  # the user discards the edit
        client.post(f"/api/tasks/{task_id}/push")
    assert _task(task_id).pr_status == "applied"
    assert "subtract" in (folder / "calc.py").read_text()
