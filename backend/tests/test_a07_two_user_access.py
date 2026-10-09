"""Sol A07 (2026-10-09): two-user access matrix.

The sharing model, defined explicitly: everyone signed in to one
installation is one trusted team — projects and tasks are shared — but a
chat belongs to the person who started it. User B (an approver, i.e. fully
authorized for the team's work) must not read, stream, continue, confirm,
stop, close, rename or delete user A's chat; it answers 404 so B cannot
even learn it exists. No AI runs: B is refused before any agent starts.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, text

from app.config import get_settings
from app.db.models import ChatSessionRecord, Project, User
from app.main import app

A, B = "a07-alice", "a07-bob"
PW = "a07-password-1"


def _fresh() -> None:
    import app.db.session as sess

    sess._engine = None
    sess._session_factory = None


def _run(fn: Any) -> Any:
    try:
        return asyncio.run(fn())
    finally:
        _fresh()


@pytest.fixture()
def team(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    from app.auth import revocation
    from app.auth.jwt import hash_password
    from app.db.session import get_async_session

    s = get_settings()
    monkeypatch.setattr(s, "jwt_auth_enabled", True)
    monkeypatch.setattr(s, "rbac_enabled", True)
    if not s.jwt_secret_key:
        monkeypatch.setattr(s, "jwt_secret_key", "x" * 48)
    revocation.invalidate()
    folder = tmp_path / "shop"
    folder.mkdir()

    async def make() -> int:
        async with get_async_session() as db:
            for u in (A, B):
                await db.merge(
                    User(
                        username=u,
                        hashed_password=hash_password(PW),
                        role="approver",
                        must_change_password=False,
                        token_version=0,
                    )
                )
            p = Project(
                name="A07 shop", local_path=str(folder), source="local_existing"
            )
            db.add(p)
            await db.commit()
            await db.refresh(p)
            return int(p.id)

    pid = _run(make)
    yield pid
    revocation.invalidate()

    async def rm() -> None:
        async with get_async_session() as db:
            rows = await db.execute(
                text("SELECT id FROM chat_sessions WHERE project_id = :p"), {"p": pid}
            )
            for (sid,) in rows:
                await db.execute(
                    text("DELETE FROM chat_messages WHERE session_id = :s"), {"s": sid}
                )
            await db.execute(
                delete(ChatSessionRecord).where(ChatSessionRecord.project_id == pid)
            )
            await db.execute(delete(Project).where(Project.id == pid))
            await db.execute(delete(User).where(User.username.in_([A, B])))
            await db.commit()

    _run(rm)


async def _token(c: httpx.AsyncClient, user: str) -> dict[str, str]:
    r = await c.post("/api/auth/login", json={"username": user, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.cookies['gridiron_token']}"}


def test_two_user_access_matrix(team: int) -> None:
    async def go() -> dict[str, int]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            alice, bob = await _token(c, A), await _token(c, B)
            r = await c.post(
                "/api/chat/sessions", json={"project_id": team}, headers=alice
            )
            assert r.status_code == 200, r.text
            sid = r.json()["session_id"]
            base = f"/api/chat/sessions/{sid}"
            bob_tries = {
                "history": await c.get(f"{base}/history", headers=bob),
                "stream": await c.get(f"{base}/stream", headers=bob),
                "message": await c.post(
                    f"{base}/messages", json={"message": "hi"}, headers=bob
                ),
                "confirm": await c.post(
                    f"{base}/confirm",
                    json={"action_id": "x", "approved": True},
                    headers=bob,
                ),
                "stop": await c.post(f"{base}/stop", headers=bob),
                "close": await c.delete(base, headers=bob),
                "rename": await c.patch(base, json={"title": "mine"}, headers=bob),
                "delete": await c.delete(f"/api/chat/history/{sid}", headers=bob),
            }
            listed_for_bob = [
                ch["id"]
                for ch in (await c.get("/api/chat/sessions", headers=bob)).json()[
                    "chats"
                ]
            ]
            out = {k: v.status_code for k, v in bob_tries.items()}
            out["bob_sees_in_list"] = int(sid in listed_for_bob)
            out["alice_history"] = (
                await c.get(f"{base}/history", headers=alice)
            ).status_code
            out["alice_rename"] = (
                await c.patch(base, json={"title": "Checkout"}, headers=alice)
            ).status_code
            # the team's shared work stays shared
            out["bob_sees_project"] = (
                await c.get(f"/api/projects/{team}", headers=bob)
            ).status_code
            return out

    out = _run(go)
    for action in (
        "history",
        "stream",
        "message",
        "confirm",
        "stop",
        "close",
        "rename",
        "delete",
    ):
        assert out[action] == 404, (action, out[action])
    assert out["bob_sees_in_list"] == 0
    assert out["alice_history"] == 200 and out["alice_rename"] == 200
    assert out["bob_sees_project"] == 200
