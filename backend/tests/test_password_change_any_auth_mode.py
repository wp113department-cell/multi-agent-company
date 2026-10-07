"""Changing a password must work in both auth modes.

Reported on the Windows Docker setup: with JWT_AUTH_ENABLED off, login
succeeded and forced a password change, but the change was refused ("A real
JWT is required"), so it was never saved. The user had to sign in with the
default and change it again every time, and the new password never worked.
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

USER = "pwcycle-user"


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
def account(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.auth.jwt import hash_password
    from app.db.session import get_async_session

    async def make() -> None:
        async with get_async_session() as db:
            await db.merge(
                User(
                    username=USER,
                    hashed_password=hash_password("first-password-1"),
                    role="admin",
                    must_change_password=True,
                )
            )
            await db.commit()

    _run(make)
    yield USER

    async def rm() -> None:
        async with get_async_session() as db:
            await db.execute(delete(User).where(User.username == USER))
            await db.commit()

    _run(rm)


def _cycle(jwt_on: bool, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    s = get_settings()
    monkeypatch.setattr(s, "jwt_auth_enabled", jwt_on)
    monkeypatch.setattr(s, "rbac_enabled", True)
    if not s.jwt_secret_key:
        monkeypatch.setattr(s, "jwt_secret_key", "x" * 48)

    async def go() -> list[int]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            a = await c.post(
                "/api/auth/login",
                json={"username": USER, "password": "first-password-1"},
            )
            b = await c.post(
                "/api/auth/change-password",
                json={
                    "current_password": "first-password-1",
                    "new_password": "Admin123",
                },
            )
            c.cookies.clear()
            d = await c.post(
                "/api/auth/login", json={"username": USER, "password": "Admin123"}
            )
            e = await c.post(
                "/api/auth/login",
                json={"username": USER, "password": "first-password-1"},
            )
            return [a.status_code, b.status_code, d.status_code, e.status_code]

    return list(_run(go))


@pytest.mark.parametrize("jwt_on", [True, False], ids=["jwt-on", "jwt-off"])
def test_new_password_is_saved_and_works_next_time(
    account: str, jwt_on: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    login, change, new_login, old_login = _cycle(jwt_on, monkeypatch)
    assert (login, change) == (200, 200)
    assert new_login == 200, "the new password must work after signing out"
    assert old_login == 401, "the old password must stop working"


def test_jwt_off_change_without_a_session_is_refused(
    account: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "jwt_auth_enabled", False)

    async def go() -> int:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            r = await c.post(
                "/api/auth/change-password",
                json={
                    "current_password": "first-password-1",
                    "new_password": "Admin123",
                },
            )
            return r.status_code

    assert _run(go) == 401


def test_jwt_off_forged_session_is_refused(
    account: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "jwt_auth_enabled", False)

    async def go() -> int:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            c.cookies.set("gridiron_token", "not.a.valid-token")
            r = await c.post(
                "/api/auth/change-password",
                json={
                    "current_password": "first-password-1",
                    "new_password": "Admin123",
                },
            )
            return r.status_code

    assert _run(go) == 401
