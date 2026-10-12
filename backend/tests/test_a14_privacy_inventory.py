"""Sol A14 (2026-10-09): privacy export and erasure tell the truth.

The export returned only identity and audit rows while tasks, epics,
projects, chats and decisions kept naming the person; erasure removed the
login and left all of that. Now the export covers the full inventory with
totals and paging, and erasure deletes the person's own chats and replaces
their name on shared team work with "erased-user" (the audit log stays,
append-only, as documented).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.main import app

USER = "a14-person"


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
def person(tmp_path: Any) -> Any:
    from app.auth.jwt import hash_password
    from app.db.models import ChatSessionRecord, DevTask, Project, User
    from app.db.repository import create_task

    async def make(s):  # type: ignore[no-untyped-def]
        await s.merge(
            User(
                username=USER, hashed_password=hash_password("x" * 12), role="approver"
            )
        )
        p = Project(
            name="A14",
            local_path=str(tmp_path),
            source="local_existing",
            created_by=USER,
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        task_ids = []
        for i in range(3):
            t = await create_task(s, f"a14 task {i}", "d")
            task_ids.append(t.id)
        await s.execute(
            text("UPDATE dev_tasks SET created_by = :u WHERE id = ANY(:ids)"),
            {"u": USER, "ids": task_ids},
        )
        s.add(
            ChatSessionRecord(
                id="a14-chat", repo_path=str(tmp_path), created_by=USER, project_id=p.id
            )
        )
        await s.commit()
        await s.execute(
            text(
                "INSERT INTO chat_messages (session_id, repo_path, role, content) "
                "VALUES ('a14-chat', :r, 'user', 'my private question')"
            ),
            {"r": str(tmp_path)},
        )
        await s.commit()
        return p.id, task_ids

    pid, task_ids = _db(make)
    yield pid, task_ids

    async def clean(s):  # type: ignore[no-untyped-def]
        await s.execute(text("DELETE FROM chat_messages WHERE session_id = 'a14-chat'"))
        await s.execute(
            delete(ChatSessionRecord).where(ChatSessionRecord.id == "a14-chat")
        )
        await s.execute(delete(DevTask).where(DevTask.id.in_(task_ids)))
        await s.execute(delete(Project).where(Project.id == pid))
        await s.execute(delete(User).where(User.username == USER))
        await s.commit()

    _db(clean)


def test_the_export_covers_everything_with_paging(
    person: Any, monkeypatch: Any
) -> None:
    from app.middleware import rbac

    monkeypatch.setattr(rbac, "require_admin", lambda: "admin")
    with TestClient(app) as client:
        app.dependency_overrides[rbac.require_admin] = lambda: "admin"
        try:
            full = client.get(f"/api/privacy/export/{USER}").json()
            page = client.get(f"/api/privacy/export/{USER}?limit=2&offset=2").json()
        finally:
            app.dependency_overrides.clear()
    assert full["chats"]["total"] == 1
    assert full["chats"]["items"][0]["messages"][0]["content"] == "my private question"
    assert full["teamWork"]["tasks"]["total"] == 3
    assert full["teamWork"]["projects"]["total"] == 1
    assert len(page["teamWork"]["tasks"]["items"]) == 1  # 3 tasks, page 2 of size 2
    assert page["teamWork"]["tasks"]["total"] == 3


def test_erasure_deletes_personal_content_and_pseudonymizes_team_work(
    person: Any,
) -> None:
    from app.middleware import rbac

    pid, task_ids = person
    with TestClient(app) as client:
        app.dependency_overrides[rbac.require_admin] = lambda: "admin"
        try:
            out = client.delete(f"/api/privacy/user/{USER}").json()
        finally:
            app.dependency_overrides.clear()
    assert out["removed"]["chats"] == 1
    assert out["pseudonymized"]["counts"]["tasks"] == 3
    assert out["pseudonymized"]["counts"]["projects"] == 1

    async def check(s):  # type: ignore[no-untyped-def]
        q = lambda sql, **p: s.execute(text(sql), p)  # noqa: E731
        chats = (
            await q("SELECT count(*) FROM chat_sessions WHERE id='a14-chat'")
        ).scalar()
        msgs = (
            await q("SELECT count(*) FROM chat_messages WHERE session_id='a14-chat'")
        ).scalar()
        named = (
            await q("SELECT count(*) FROM dev_tasks WHERE created_by = :u", u=USER)
        ).scalar()
        kept = (
            await q(
                "SELECT count(*) FROM dev_tasks WHERE id = ANY(:i) AND created_by = 'erased-user'",
                i=task_ids,
            )
        ).scalar()
        return chats, msgs, named, kept

    chats, msgs, named, kept = _db(check)
    assert (chats, msgs) == (0, 0)  # the private chat is gone
    assert named == 0 and kept == 3  # the team's tasks stay, unnamed
