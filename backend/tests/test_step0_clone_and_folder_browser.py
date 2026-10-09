"""Step 0 (planned 2026-10-06, written 2026-10-09): tests for the fast clone
and the folder browser that shipped on 2026-10-06 without their own tests.

- a clone is shallow by default (`--depth 1 --single-branch`);
- "full history" clones everything;
- a server without shallow support falls back to a full clone;
- picking a non-empty folder clones into `<folder>/<repo-name>`;
- the folder browser's start is `GET /api/console/workspace/root`.

git itself is replaced by a recorder; nothing is downloaded.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app


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
def repo_row(tmp_path: Path):  # type: ignore[no-untyped-def]
    from sqlalchemy import delete

    from app.db.models import Repo

    async def make(s):  # type: ignore[no-untyped-def]
        r = Repo(
            github_url="https://github.com/step0/demo",
            name="demo",
            local_path=str(tmp_path / "demo"),
            status="cloning",
        )
        s.add(r)
        await s.commit()
        await s.refresh(r)
        return r.id

    rid = _db(make)
    yield rid, str(tmp_path / "demo")

    async def clean(s):  # type: ignore[no-untyped-def]
        await s.execute(delete(Repo).where(Repo.id == rid))
        await s.commit()

    _db(clean)


def _clone(
    monkeypatch: pytest.MonkeyPatch,
    repo_id: int,
    path: str,
    full_history: bool,
    replies: list[tuple[int, bytes]],
) -> list[list[str]]:
    from app.api import repo as repo_api
    from app.services import git_service

    calls: list[list[str]] = []

    async def fake_git(cmd: list[str], cwd: Any, env: Any, timeout: float) -> Any:
        calls.append(list(cmd))
        rc, err = replies[min(len(calls), len(replies)) - 1]
        return rc, b"", err, False

    monkeypatch.setattr(git_service, "run_git_process", fake_git)
    asyncio.run(
        repo_api._clone_and_activate(
            repo_id, "https://github.com/step0/demo", path, full_history=full_history
        )
    )
    return calls


def test_a_clone_is_shallow_by_default(
    repo_row: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid, path = repo_row
    calls = _clone(monkeypatch, rid, path, False, [(1, b"stop here")])
    assert calls[0][:2] == ["git", "clone"]
    assert "--depth" in calls[0] and calls[0][calls[0].index("--depth") + 1] == "1"
    assert "--single-branch" in calls[0]


def test_full_history_clones_everything(
    repo_row: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid, path = repo_row
    calls = _clone(monkeypatch, rid, path, True, [(1, b"stop here")])
    assert "--depth" not in calls[0] and "--single-branch" not in calls[0]


def test_no_shallow_support_falls_back_to_a_full_clone(
    repo_row: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid, path = repo_row
    calls = _clone(
        monkeypatch,
        rid,
        path,
        False,
        [
            (128, b"fatal: dumb http transport does not support shallow capabilities"),
            (1, b"x"),
        ],
    )
    assert len(calls) == 2
    assert "--depth" in calls[0] and "--depth" not in calls[1]


def test_a_non_empty_folder_gets_a_sub_folder_named_after_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import delete

    from app.api import repo as repo_api
    from app.config import get_settings
    from app.db.models import Repo

    settings = get_settings()
    monkeypatch.setattr(settings, "allowed_workspace_parent", str(tmp_path))
    started: list[Any] = []

    async def no_clone(*a: Any, **k: Any) -> None:
        started.append(a)

    monkeypatch.setattr(repo_api, "_clone_and_activate", no_clone)
    folder = tmp_path / "my-projects"
    folder.mkdir()
    (folder / "notes.txt").write_text("already here\n")
    with TestClient(app) as client:
        r = client.post(
            "/api/repo/clone",
            json={
                "github_url": "https://github.com/step0/shop",
                "dest_path": str(folder),
            },
        )
    assert r.status_code in (200, 201, 202), r.text
    body = r.json()
    assert body["localPath"] == str(folder / "shop")

    async def clean(s):  # type: ignore[no-untyped-def]
        await s.execute(delete(Repo).where(Repo.id == body["id"]))
        await s.commit()

    _db(clean)


def test_the_folder_browser_starts_at_the_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "allowed_workspace_parent", "/workspace")
    monkeypatch.setattr(
        settings,
        "workspace_host_label",
        "C:\\Users\\me\\Documents\\multi-agent-workspace",
    )
    with TestClient(app) as client:
        body = client.get("/api/console/workspace/root").json()
    assert body == {
        "root": "/workspace",
        "host_label": "C:\\Users\\me\\Documents\\multi-agent-workspace",
    }
