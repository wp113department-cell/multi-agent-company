"""W4 — the user's unsaved edits (2026-10-09).

A task works in its own worktree, which starts from the project folder's
last commit, so edits the user hasn't committed were silently invisible to
the agents. Start now checks first: with unsaved edits nothing starts and
the user chooses "save them first" (a commit that never includes .env or
keys) or "start without them".

No AI runs here: the job launcher is replaced by a recorder.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.git_local_apply import save_changes, unsaved_changes


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _folder(tmp_path: Path) -> Path:
    folder = tmp_path / "proj"
    folder.mkdir()
    _git(folder, "init", "-q", "-b", "main")
    (folder / "app.py").write_text("x = 1\n")
    (folder / ".gitignore").write_text("build/\n")
    _git(folder, "add", "-A")
    _git(folder, "commit", "-q", "-m", "start")
    return folder


def test_unsaved_changes_lists_edited_and_new_files_not_ignored_ones(
    tmp_path: Path,
) -> None:
    folder = _folder(tmp_path)
    assert asyncio.run(unsaved_changes(str(folder))) == []
    (folder / "app.py").write_text("x = 2\n")
    (folder / "new.py").write_text("y = 1\n")
    (folder / "build").mkdir()
    (folder / "build" / "out.bin").write_text("z")
    assert sorted(asyncio.run(unsaved_changes(str(folder)))) == ["app.py", "new.py"]


def test_not_a_repository_has_nothing_to_report(tmp_path: Path) -> None:
    assert asyncio.run(unsaved_changes(str(tmp_path))) == []


def test_saving_commits_the_edits_but_never_secrets(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    (folder / "app.py").write_text("x = 2\n")
    (folder / ".env").write_text("SECRET=1\n")
    (folder / "sub").mkdir()
    (folder / "sub" / ".env.local").write_text("SECRET=2\n")
    (folder / "server.key").write_text("k\n")
    result = asyncio.run(save_changes(str(folder), 7))
    assert result.applied
    assert _git(folder, "log", "-1", "--format=%s") == "Save my changes before task #7"
    committed = _git(folder, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert committed == ["app.py"]
    assert (folder / ".env").exists()  # left in place, just not committed


# -- wiring through POST /api/tasks/{id}/run ----------------------------------


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
def launched(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    from app.api import tasks

    calls: list[Any] = []

    async def record(*args: Any, **kwargs: Any) -> None:
        calls.append(args)

    monkeypatch.setattr(tasks, "dispatch_job", record)
    return calls


def _make_task(folder: Path, with_project: bool) -> tuple[int, int | None, int]:
    from sqlalchemy import update

    from app.db.models import DevTask, Project, Repo
    from app.db.repository import create_task

    async def make(s):  # type: ignore[no-untyped-def]
        repo = Repo(name="w4", local_path=str(folder), status="ready")
        s.add(repo)
        await s.commit()
        await s.refresh(repo)
        project_id = None
        if with_project:
            project = Project(
                name="W4",
                repo_id=repo.id,
                local_path=str(folder),
                source="local_existing",
            )
            s.add(project)
            await s.commit()
            await s.refresh(project)
            project_id = project.id
        task = await create_task(s, "w4 task", "desc")
        await s.execute(
            update(DevTask)
            .where(DevTask.id == task.id)
            .values(repo_id=repo.id, project_id=project_id)
        )
        await s.commit()
        return task.id, project_id, repo.id

    return _db(make)


def _cleanup(task_id: int, project_id: int | None, repo_id: int) -> None:
    from sqlalchemy import delete

    from app.db.models import DevTask, Project, Repo, TaskLog

    async def clean(s):  # type: ignore[no-untyped-def]
        await s.execute(delete(TaskLog).where(TaskLog.task_id == task_id))
        await s.execute(delete(DevTask).where(DevTask.id == task_id))
        if project_id:
            await s.execute(delete(Project).where(Project.id == project_id))
        await s.execute(delete(Repo).where(Repo.id == repo_id))
        await s.commit()

    _db(clean)


def _status(task_id: int) -> str:
    from app.db.models import DevTask

    async def get(s):  # type: ignore[no-untyped-def]
        return (await s.get(DevTask, task_id)).status

    return str(_db(get))


def _run(task_id: int, body: dict[str, Any]) -> dict[str, Any]:
    with TestClient(app) as client:
        r = client.post(f"/api/tasks/{task_id}/run", json=body)
        assert r.status_code == 200, r.text
        return dict(r.json())


def test_start_stops_and_lists_unsaved_edits(
    tmp_path: Path, launched: list[Any]
) -> None:
    folder = _folder(tmp_path)
    (folder / "app.py").write_text("x = 2\n")
    ids = _make_task(folder, with_project=True)
    try:
        r = _run(ids[0], {})
        assert r["triggered"] is False
        assert r["unsavedChanges"] == ["app.py"] and r["unsavedCount"] == 1
        assert _status(ids[0]) == "pending"
        assert launched == []
    finally:
        _cleanup(*ids)


def test_start_without_them(tmp_path: Path, launched: list[Any]) -> None:
    folder = _folder(tmp_path)
    (folder / "app.py").write_text("x = 2\n")
    ids = _make_task(folder, with_project=True)
    try:
        assert _run(ids[0], {"unsaved": "ignore"})["triggered"] is True
        assert _status(ids[0]) == "planning"
        assert len(launched) == 1
        assert _git(folder, "log", "-1", "--format=%s") == "start"  # nothing committed
    finally:
        _cleanup(*ids)


def test_save_them_first_then_start(tmp_path: Path, launched: list[Any]) -> None:
    folder = _folder(tmp_path)
    (folder / "app.py").write_text("x = 2\n")
    ids = _make_task(folder, with_project=True)
    try:
        assert _run(ids[0], {"unsaved": "save"})["triggered"] is True
        assert (
            _git(folder, "log", "-1", "--format=%s")
            == f"Save my changes before task #{ids[0]}"
        )
        assert _git(folder, "status", "--porcelain") == ""
        assert len(launched) == 1
    finally:
        _cleanup(*ids)


def test_a_clean_folder_starts_straight_away(
    tmp_path: Path, launched: list[Any]
) -> None:
    ids = _make_task(_folder(tmp_path), with_project=True)
    try:
        assert _run(ids[0], {})["triggered"] is True
    finally:
        _cleanup(*ids)


def test_tasks_outside_a_project_behave_as_before(
    tmp_path: Path, launched: list[Any]
) -> None:
    folder = _folder(tmp_path)
    (folder / "app.py").write_text("x = 2\n")
    ids = _make_task(folder, with_project=False)
    try:
        assert _run(ids[0], {})["triggered"] is True
    finally:
        _cleanup(*ids)
