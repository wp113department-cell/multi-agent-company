"""C2 — the list of past chats (2026-10-09).

Chats lived only in memory, so there was no list to reopen, rename or
delete them. Now each chat has a record (chat_sessions): created with the
chat, named after its first message, moved to the top by each message.
"Close" (DELETE /sessions/{id}) keeps the history; "delete" removes it.
No AI runs here.
"""

from __future__ import annotations

import asyncio
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


def _register_folder(path: str) -> int:
    """Sol A03: chats only open in a registered project folder."""
    from app.db.models import Project

    async def make(s):  # type: ignore[no-untyped-def]
        p = Project(name="chat test", local_path=path, source="local_existing")
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p.id

    return int(_db(make))


def _unregister(project_id: int) -> None:
    from sqlalchemy import delete

    from app.db.models import Project

    async def drop(s):  # type: ignore[no-untyped-def]
        await s.execute(delete(Project).where(Project.id == project_id))
        await s.commit()

    _db(drop)


@pytest.fixture
def chats(tmp_path: Any):  # type: ignore[no-untyped-def]
    created: list[str] = []
    project_id = _register_folder(str(tmp_path))
    yield created, str(tmp_path)
    _unregister(project_id)

    async def clean(s):  # type: ignore[no-untyped-def]
        from sqlalchemy import delete, text

        from app.db.models import ChatSessionRecord

        for sid in created:
            await s.execute(
                delete(ChatSessionRecord).where(ChatSessionRecord.id == sid)
            )
            await s.execute(
                text("DELETE FROM chat_messages WHERE session_id = :s"), {"s": sid}
            )
        await s.commit()

    _db(clean)


def _new_chat(client: TestClient, created: list[str], path: str) -> str:
    r = client.post("/api/chat/sessions", json={"repo_path": path})
    assert r.status_code == 200, r.text
    sid = str(r.json()["session_id"])
    created.append(sid)
    return sid


def _touch(sid: str, message: str) -> None:
    from app.api.chat import _touch_chat_record

    async def go(s):  # type: ignore[no-untyped-def]
        await _touch_chat_record(s, sid, message)

    _db(go)


def _listed(client: TestClient) -> list[dict[str, Any]]:
    return list(client.get("/api/chat/sessions").json()["chats"])


def test_a_new_chat_is_listed_and_named_by_its_first_message(chats) -> None:  # type: ignore[no-untyped-def]
    created, path = chats
    with TestClient(app) as client:
        sid = _new_chat(client, created, path)
        assert any(c["id"] == sid and c["title"] == "New chat" for c in _listed(client))
        _touch(sid, "Add a dark mode toggle\nand make it remembered")
        _touch(sid, "second message never renames it")
        mine = next(c for c in _listed(client) if c["id"] == sid)
    assert mine["title"] == "Add a dark mode toggle"


def test_newest_chat_comes_first(chats) -> None:  # type: ignore[no-untyped-def]
    created, path = chats
    with TestClient(app) as client:
        older = _new_chat(client, created, path)
        newer = _new_chat(client, created, path)
        _touch(older, "bring me back to the top")
        ids = [c["id"] for c in _listed(client)]
    assert ids.index(older) < ids.index(newer)


def test_rename_and_delete(chats) -> None:  # type: ignore[no-untyped-def]
    created, path = chats
    with TestClient(app) as client:
        sid = _new_chat(client, created, path)
        r = client.patch(f"/api/chat/sessions/{sid}", json={"title": "Release notes"})
        assert r.status_code == 200 and r.json()["title"] == "Release notes"
        assert (
            client.patch(f"/api/chat/sessions/{sid}", json={"title": " "}).status_code
            == 400
        )
        assert client.delete(f"/api/chat/history/{sid}").status_code == 200
        assert all(c["id"] != sid for c in _listed(client))
        assert (
            client.patch(f"/api/chat/sessions/{sid}", json={"title": "x"}).status_code
            == 404
        )


def test_closing_a_chat_keeps_it_in_the_list(chats) -> None:  # type: ignore[no-untyped-def]
    created, path = chats
    with TestClient(app) as client:
        sid = _new_chat(client, created, path)
        assert client.delete(f"/api/chat/sessions/{sid}").status_code == 200
        assert any(c["id"] == sid for c in _listed(client))


def test_a_closed_chat_can_be_reopened(chats) -> None:  # type: ignore[no-untyped-def]
    """Reopening rebuilds the conversation from its record, even when it
    never got a message (so chat_messages has nothing to go on)."""
    from app.api.chat import _require_session_restoring
    from app.models.chat import delete_session, get_session

    created, path = chats
    with TestClient(app) as client:
        sid = _new_chat(client, created, path)
        client.delete(f"/api/chat/sessions/{sid}")
    assert get_session(sid) is None
    import app.db.session as sess

    # the shared engine is bound to the TestClient's event loop; this call
    # runs on a new loop (production has one loop and never does this)
    sess._engine = None
    sess._session_factory = None
    restored = asyncio.run(_require_session_restoring(sid))
    assert restored.session_id == sid and restored.repo_path == path
    delete_session(sid)


def test_another_users_chat_is_not_listed_or_editable(chats) -> None:  # type: ignore[no-untyped-def]
    from app.db.models import ChatSessionRecord

    created, path = chats

    async def other(s):  # type: ignore[no-untyped-def]
        s.add(
            ChatSessionRecord(
                id="c2-other-user", repo_path=path, created_by="someone-else"
            )
        )
        await s.commit()

    _db(other)
    created.append("c2-other-user")
    with TestClient(app) as client:
        assert all(c["id"] != "c2-other-user" for c in _listed(client))
        r = client.patch("/api/chat/sessions/c2-other-user", json={"title": "mine now"})
        assert r.status_code == 404
        assert client.delete("/api/chat/history/c2-other-user").status_code == 404
