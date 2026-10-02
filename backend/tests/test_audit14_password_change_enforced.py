"""Production audit 14 (REPRO-14-006): "must change password" is enforced.

Before: the seeded admin (must_change_password=True) could use the whole API
without ever changing the default password; only the login response mentioned
the flag. Real Postgres + real JWT login.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db.session import new_isolated_async_engine
from app.middleware.password_change import forget


async def _make(name: str, pw: str, must_change: bool) -> None:
    from app.auth.jwt import hash_password

    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine)() as db:
            await db.execute(
                text(
                    "INSERT INTO users (username, hashed_password, role, must_change_password) "
                    "VALUES (:u, :h, 'approver', :m)"
                ),
                {"u": name, "h": hash_password(pw), "m": must_change},
            )
            await db.commit()
    finally:
        await engine.dispose()


async def _drop(names: list[str]) -> None:
    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine)() as db:
            await db.execute(
                text("DELETE FROM users WHERE username = ANY(:n)"), {"n": names}
            )
            await db.commit()
    finally:
        await engine.dispose()


@pytest.fixture()
def jwt_on(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "jwt_auth_enabled", True)
    if not s.jwt_secret_key:
        monkeypatch.setattr(s, "jwt_secret_key", "a" * 64)
    forget()


def test_flagged_account_is_blocked_until_the_password_is_changed(jwt_on: None) -> None:
    from app.main import app

    flagged, normal = (
        f"a14-flag-{uuid.uuid4().hex[:6]}",
        f"a14-ok-{uuid.uuid4().hex[:6]}",
    )
    asyncio.run(_make(flagged, "Default-Pass-1", True))
    asyncio.run(_make(normal, "Normal-Pass-1", False))
    try:
        with TestClient(app) as c:
            r = c.post(
                "/api/auth/login",
                json={"username": flagged, "password": "Default-Pass-1"},
            )
            assert r.status_code == 200 and r.json()["must_change_password"] is True

            blocked = c.get("/api/tasks?limit=1")
            assert blocked.status_code == 403
            assert blocked.json()["error"]["reason"] == "password_change_required"
            # refresh must not be a way around it
            assert c.post("/api/auth/refresh").status_code == 403

            r = c.post(
                "/api/auth/change-password",
                json={
                    "current_password": "Default-Pass-1",
                    "new_password": "Brand-New-Pass-2",
                },
            )
            assert r.status_code == 200, r.text
            assert (
                c.get("/api/tasks?limit=1").status_code == 200
            ), "not unlocked after change"

        with TestClient(app) as c2:
            c2.post(
                "/api/auth/login",
                json={"username": normal, "password": "Normal-Pass-1"},
            )
            assert c2.get("/api/tasks?limit=1").status_code == 200
    finally:
        asyncio.run(_drop([flagged, normal]))
        forget()
