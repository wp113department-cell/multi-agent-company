"""Sol A12 (2026-10-09): an old sign-in token stops working.

Signing out only removed the browser cookie, and changing the password did
not touch already-issued tokens — a copied token kept full access for its
whole lifetime (24 h by default), including the right to refresh itself.
Tokens now carry the account's token_version, which signing out and
changing the password raise.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from sqlalchemy import delete

from app.config import get_settings
from app.db.models import User
from app.main import app

USER = "a12-user"
PW1 = "first-password-1"
PW2 = "second-password-2"


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
def jwt_on(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.auth import revocation
    from app.auth.jwt import hash_password
    from app.db.session import get_async_session

    s = get_settings()
    monkeypatch.setattr(s, "jwt_auth_enabled", True)
    monkeypatch.setattr(s, "rbac_enabled", True)
    monkeypatch.setattr(s, "jwt_revalidate_against_db", True)
    if not s.jwt_secret_key:
        monkeypatch.setattr(s, "jwt_secret_key", "x" * 48)
    revocation.invalidate()

    async def make() -> None:
        async with get_async_session() as db:
            await db.merge(
                User(
                    username=USER,
                    hashed_password=hash_password(PW1),
                    role="admin",
                    must_change_password=False,
                    token_version=0,
                )
            )
            await db.commit()

    _run(make)
    yield
    revocation.invalidate()

    async def rm() -> None:
        async with get_async_session() as db:
            await db.execute(delete(User).where(User.username == USER))
            await db.commit()

    _run(rm)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    )


async def _login(c: httpx.AsyncClient, pw: str) -> str:
    r = await c.post("/api/auth/login", json={"username": USER, "password": pw})
    assert r.status_code == 200, r.text
    return str(r.cookies["gridiron_token"])


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_a_copied_token_dies_when_the_password_changes(jwt_on: Any) -> None:
    async def go() -> tuple[int, int, int, int]:
        async with _client() as c:
            stolen = await _login(c, PW1)
            before = (await c.get("/api/tasks", headers=_bearer(stolen))).status_code
            r = await c.post(
                "/api/auth/change-password",
                json={"current_password": PW1, "new_password": PW2},
                headers=_bearer(stolen),
            )
            assert r.status_code == 200, r.text
            fresh = str(r.cookies["gridiron_token"])
            after_old = (await c.get("/api/tasks", headers=_bearer(stolen))).status_code
            after_new = (await c.get("/api/tasks", headers=_bearer(fresh))).status_code
            refresh_old = (
                await c.post("/api/auth/refresh", headers=_bearer(stolen))
            ).status_code
            return before, after_old, after_new, refresh_old

    before, after_old, after_new, refresh_old = _run(go)
    assert before == 200
    assert after_old == 401  # the copied token is dead
    assert after_new == 200  # this browser stays signed in
    assert refresh_old == 401  # and it cannot be refreshed back to life


def test_signing_out_ends_every_session(jwt_on: Any) -> None:
    async def go() -> tuple[int, int, int]:
        async with _client() as c:
            laptop = await _login(c, PW1)
            phone = await _login(c, PW1)
            r = await c.post("/api/auth/logout", headers=_bearer(laptop))
            assert r.status_code == 204
            a = (await c.get("/api/tasks", headers=_bearer(laptop))).status_code
            b = (await c.get("/api/tasks", headers=_bearer(phone))).status_code
            again = await _login(c, PW1)
            d = (await c.get("/api/tasks", headers=_bearer(again))).status_code
            return a, b, d

    a, b, d = _run(go)
    assert (a, b) == (401, 401)
    assert d == 200  # signing in again works


def test_the_message_says_what_happened(jwt_on: Any) -> None:
    async def go() -> Any:
        async with _client() as c:
            token = await _login(c, PW1)
            await c.post("/api/auth/logout", headers=_bearer(token))
            return (await c.get("/api/tasks", headers=_bearer(token))).json()

    body = _run(go)
    assert "sign in again" in str(body)


def test_tokens_from_before_the_upgrade_still_work(jwt_on: Any) -> None:
    """Issued before A12 (no "tv"): counts as version 0, so the upgrade
    itself signs nobody out."""
    from app.auth.jwt import create_access_token

    legacy = create_access_token({"sub": USER, "role": "admin"})

    async def go() -> int:
        async with _client() as c:
            return (await c.get("/api/tasks", headers=_bearer(legacy))).status_code

    assert _run(go) == 200
