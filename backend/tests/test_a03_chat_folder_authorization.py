"""Sol A03 (2026-10-09): a chat — and the terminal it opens, which mounts
the chat's folder into the sandbox — used to accept ANY folder path the
caller sent. The folder is now resolved on the server: from a project, or
for a path only when it is a registered project/repository folder (or
inside one); nonexistent and symlinked folders are refused."""

from __future__ import annotations

import asyncio
import os
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
def project(tmp_path: Path):  # type: ignore[no-untyped-def]
    from sqlalchemy import delete

    from app.db.models import Project

    folder = tmp_path / "shop"
    (folder / "src").mkdir(parents=True)

    async def make(s):  # type: ignore[no-untyped-def]
        p = Project(name="A03", local_path=str(folder), source="local_existing")
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p.id

    pid = _db(make)
    created: list[str] = []
    yield pid, folder, created

    async def clean(s):  # type: ignore[no-untyped-def]
        from sqlalchemy import text

        from app.db.models import ChatSessionRecord

        for sid in created:
            await s.execute(
                delete(ChatSessionRecord).where(ChatSessionRecord.id == sid)
            )
            await s.execute(
                text("DELETE FROM chat_messages WHERE session_id = :s"), {"s": sid}
            )
        await s.execute(delete(Project).where(Project.id == pid))
        await s.commit()

    _db(clean)


def _open(client: TestClient, created: list[str], body: dict[str, Any]) -> Any:
    r = client.post("/api/chat/sessions", json=body)
    if r.status_code == 200:
        created.append(r.json()["session_id"])
    return r


def _folder_of(session_id: str) -> str:
    from app.models.chat import get_session

    s = get_session(session_id)
    assert s is not None
    return s.repo_path


def test_a_project_chat_gets_the_projects_folder(project: Any) -> None:
    pid, folder, created = project
    with TestClient(app) as client:
        r = _open(client, created, {"project_id": pid, "repo_path": "/etc"})
    assert r.status_code == 200
    # the server's answer, not the caller's path
    assert _folder_of(r.json()["session_id"]) == str(folder)


def test_a_registered_folder_or_sub_folder_is_accepted(project: Any) -> None:
    _, folder, created = project
    with TestClient(app) as client:
        assert _open(client, created, {"repo_path": str(folder)}).status_code == 200
        assert (
            _open(client, created, {"repo_path": str(folder / "src")}).status_code
            == 200
        )


@pytest.mark.parametrize("path", ["/", "/etc", "/home", "/tmp"])
def test_any_other_folder_is_refused(project: Any, path: str) -> None:
    _, _, created = project
    with TestClient(app) as client:
        r = _open(client, created, {"repo_path": path})
    assert r.status_code == 403


def test_a_sibling_folder_with_a_similar_name_is_refused(
    project: Any, tmp_path: Path
) -> None:
    _, folder, created = project
    sibling = Path(str(folder) + "-evil")
    sibling.mkdir()
    with TestClient(app) as client:
        assert _open(client, created, {"repo_path": str(sibling)}).status_code == 403


def test_a_symlink_into_another_place_is_refused(project: Any, tmp_path: Path) -> None:
    _, folder, created = project
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, folder / "link")
    with TestClient(app) as client:
        assert (
            _open(client, created, {"repo_path": str(folder / "link")}).status_code
            == 403
        )


def test_a_folder_that_does_not_exist_or_no_project_is_refused(project: Any) -> None:
    _, folder, created = project
    with TestClient(app) as client:
        assert (
            _open(client, created, {"repo_path": str(folder / "gone")}).status_code
            == 400
        )
        assert _open(client, created, {}).status_code == 400
        assert _open(client, created, {"project_id": 999999999}).status_code == 404
