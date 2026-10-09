"""C3 — memory the user can see and edit (2026-10-09).

The chat learned from every turn, but that memory was invisible and found
only by similarity. Project notes are the explicit part: short facts the
user writes down; every chat in the project gets all of them with every
message. They are removed with the project. No AI runs here.
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
def project(tmp_path: Path):  # type: ignore[no-untyped-def]
    from app.db.models import Project

    async def make(s):  # type: ignore[no-untyped-def]
        p = Project(name="C3", local_path=str(tmp_path), source="local_existing")
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p.id

    pid = _db(make)
    yield pid, str(tmp_path)
    with TestClient(app) as client:
        client.delete(f"/api/projects/{pid}")


def test_notes_can_be_added_listed_and_forgotten(project) -> None:  # type: ignore[no-untyped-def]
    pid, _ = project
    with TestClient(app) as client:
        r = client.post(f"/api/projects/{pid}/notes", json={"text": "  We use   pnpm  "})
        assert r.status_code == 201
        note = r.json()["notes"][0]
        assert note["text"] == "We use pnpm"
        assert client.get(f"/api/projects/{pid}/notes").json()["notes"] == [note]
        after = client.delete(f"/api/projects/{pid}/notes/{note['id']}").json()["notes"]
        assert after == []


def test_limits(project) -> None:  # type: ignore[no-untyped-def]
    pid, _ = project
    with TestClient(app) as client:
        assert client.post(f"/api/projects/{pid}/notes", json={"text": ""}).status_code == 422
        for i in range(30):
            client.post(f"/api/projects/{pid}/notes", json={"text": f"note {i}"})
        r = client.post(f"/api/projects/{pid}/notes", json={"text": "one too many"})
        assert r.status_code == 400 and "up to 30" in r.json()["error"]["message"]
        assert client.get("/api/projects/999999999/notes").status_code == 404


def test_every_chat_in_the_project_gets_the_notes(project) -> None:  # type: ignore[no-untyped-def]
    from app.agents.chat_agent import ChatAgent
    from app.models.chat import create_session, delete_session

    pid, folder = project
    with TestClient(app) as client:
        client.post(f"/api/projects/{pid}/notes", json={"text": "Never touch payments/"})
        client.post(f"/api/projects/{pid}/notes", json={"text": "We use pnpm"})
    session = create_session(repo_path=folder)
    try:
        agent: Any = ChatAgent.__new__(ChatAgent)
        agent.session = session
        block = asyncio.run(agent._project_notes_context())
    finally:
        delete_session(session.session_id)
    assert block.startswith("## Project notes")
    assert "- Never touch payments/" in block and "- We use pnpm" in block


def test_a_chat_outside_any_project_gets_none(tmp_path: Path) -> None:
    from app.agents.chat_agent import ChatAgent
    from app.models.chat import create_session, delete_session

    session = create_session(repo_path=str(tmp_path / "no-project"))
    try:
        agent: Any = ChatAgent.__new__(ChatAgent)
        agent.session = session
        assert asyncio.run(agent._project_notes_context()) == ""
    finally:
        delete_session(session.session_id)


def test_deleting_the_project_removes_its_notes(project) -> None:  # type: ignore[no-untyped-def]
    from app.db.repository import get_setting

    pid, _ = project
    with TestClient(app) as client:
        client.post(f"/api/projects/{pid}/notes", json={"text": "temporary"})
        client.delete(f"/api/projects/{pid}")

    async def read(s):  # type: ignore[no-untyped-def]
        return await get_setting(s, f"project-notes:{pid}")

    assert _db(read) is None
