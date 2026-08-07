"""AUDIT_Q_BATCH11 §96 "Compliance readiness" — proves app/api/privacy.py's
GDPR/CCPA export and erasure endpoints work end-to-end against the real
data model (system_settings.auth_users, user_roles, audit_log), not a mock.

Uses FastAPI dependency_overrides only for the auth dependencies
(require_approver/get_current_user — standard practice, avoids needing a
real JWT) while leaving get_db pointed at the real dev database.

Seeding/verification queries run through their OWN isolated
create_async_engine (via a small sync-wrapping helper), never the shared
app.db.session singleton — TestClient(app) drives the app's real endpoints
through its own internal event loop, and reusing the shared engine
singleton directly from a second, different loop is exactly the
"RuntimeError: got Future attached to a different loop" hazard
test_audit_log_migration.py's own module docstring documents (and this
test hit for real before this fix). Keeping seeding fully isolated and
synchronous (asyncio.run per call, own engine disposed each time) sidesteps
it entirely rather than trying to share a loop with TestClient.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.dependencies import CurrentUser, get_current_user
from app.config import get_settings
from app.fleet.audit_log import AuditEntry, AuditLog
from app.main import app
from app.middleware.rbac import require_approver


def _run(coro: Any) -> Any:
    """Runs one isolated async DB operation to completion on its own fresh
    event loop + engine — see module docstring for why this must never
    reuse app.db.session's shared singleton."""
    return asyncio.run(coro)


def _reset_global_session_factory() -> None:
    """AuditLog._write_to_db() (called from _seed(), below) uses
    app.db.session's process-wide engine/session-factory singleton
    internally, unlike this file's own isolated seeding engines — binding
    it to *this* asyncio.run() call's now-closed loop. Reset it so
    TestClient(app)'s own, separate loop gets a fresh one instead of
    inheriting a dead one (same fix test_audit_log_migration.py already
    established for the same underlying hazard)."""
    import app.db.session as _sess

    _sess._engine = None
    _sess._session_factory = None


async def _seed(username: str, audit_entry: AuditEntry) -> None:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT value FROM system_settings WHERE key = 'auth_users'")
            )
            existing_raw = row.scalar_one_or_none()
            existing = json.loads(existing_raw) if existing_raw else []
            existing.append(
                {
                    "username": username,
                    "hashed_password": "not-a-real-hash",
                    "role": "viewer",
                    "must_change_password": True,
                }
            )
            await conn.execute(
                text(
                    "INSERT INTO system_settings (key, value) VALUES "
                    "('auth_users', :v) ON CONFLICT (key) DO UPDATE SET "
                    "value = EXCLUDED.value"
                ),
                {"v": json.dumps(existing)},
            )
            await conn.execute(
                text("INSERT INTO user_roles (user_id, role) VALUES (:u, 'viewer')"),
                {"u": username},
            )
    finally:
        await engine.dispose()

    log = AuditLog()
    await log._write_to_db(audit_entry)


async def _verify_erased(username: str, audit_entry_id: str) -> tuple[bool, bool, bool]:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            row = await conn.execute(
                text("SELECT value FROM system_settings WHERE key = 'auth_users'")
            )
            remaining = json.loads(row.scalar_one_or_none() or "[]")
            identity_gone = all(u.get("username") != username for u in remaining)

            role_row = (
                await conn.execute(
                    text("SELECT 1 FROM user_roles WHERE user_id = :u"), {"u": username}
                )
            ).scalar_one_or_none()
            role_gone = role_row is None

            audit_row = (
                await conn.execute(
                    text("SELECT 1 FROM audit_log WHERE entry_id = :id"),
                    {"id": audit_entry_id},
                )
            ).scalar_one_or_none()
            audit_survives = audit_row is not None
        return identity_gone, role_gone, audit_survives
    finally:
        await engine.dispose()


async def _cleanup(username: str) -> None:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT value FROM system_settings WHERE key = 'auth_users'")
            )
            existing_raw = row.scalar_one_or_none()
            if existing_raw:
                cleaned = [
                    u for u in json.loads(existing_raw) if u.get("username") != username
                ]
                await conn.execute(
                    text(
                        "INSERT INTO system_settings (key, value) VALUES "
                        "('auth_users', :v) ON CONFLICT (key) DO UPDATE SET "
                        "value = EXCLUDED.value"
                    ),
                    {"v": json.dumps(cleaned)},
                )
            await conn.execute(
                text("DELETE FROM user_roles WHERE user_id = :u"), {"u": username}
            )
            await conn.execute(text("SET LOCAL audit_log.allow_mutation = 'true'"))
            await conn.execute(
                text("DELETE FROM audit_log WHERE agent_name = :u"), {"u": username}
            )
    finally:
        await engine.dispose()


@pytest.fixture
def privacy_client():
    app.dependency_overrides[require_approver] = lambda: "test-approver"
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(require_approver, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_export_and_erase_a_real_user(privacy_client: TestClient) -> None:
    username = f"privacy-test-{uuid.uuid4().hex[:8]}"
    audit_entry = AuditEntry(
        action_type="test_action",
        agent_name=username,
        description="an action attributable to the privacy test user",
    )
    try:
        # TestClient(app)'s lifespan startup (fixture setup, above) already
        # bound app.db.session's shared singleton to TestClient's own loop —
        # reset it first so _seed()'s AuditLog()._write_to_db() call (which
        # uses that same shared singleton) gets a fresh engine on ITS OWN
        # throwaway asyncio.run() loop instead of silently cross-loop-
        # failing against TestClient's (AuditLog.append()/_write_to_db()
        # swallow all exceptions by design, so that failure would otherwise
        # be invisible — this bit real before this fix, see module docstring).
        _reset_global_session_factory()
        _run(_seed(username, audit_entry))
        _reset_global_session_factory()

        # --- Export (admin, on behalf of another user) ---
        resp = privacy_client.get(f"/api/privacy/export/{username}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["identity"]["username"] == username
        assert data["identity"]["role"] == "viewer"
        assert "hashed_password" not in data["identity"]
        assert data["userRole"]["userId"] == username
        assert any(
            e["entry_id"] == audit_entry.entry_id
            for e in data["attributableAuditEntries"]
        )

        # --- Export (self-service) ---
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            username=username, role="viewer", is_authenticated=True
        )
        resp_me = privacy_client.get("/api/privacy/export/me")
        assert resp_me.status_code == 200, resp_me.text
        assert resp_me.json()["username"] == username

        # --- Erasure ---
        resp_del = privacy_client.delete(f"/api/privacy/user/{username}")
        assert resp_del.status_code == 200, resp_del.text
        del_data = resp_del.json()
        assert del_data["removed"]["authCredentials"] is True
        assert del_data["removed"]["userRole"] is True
        assert del_data["retained"]["auditLogEntries"] is True

        identity_gone, role_gone, audit_survives = _run(
            _verify_erased(username, audit_entry.entry_id)
        )
        assert identity_gone, "auth_users entry must be removed"
        assert role_gone, "user_roles row must be removed"
        assert audit_survives, (
            "audit_log must NOT be deleted — retained by design (append-only, "
            "legal-obligation basis)"
        )

        # Erasing an already-erased user is a real 404, not a silent no-op
        resp_again = privacy_client.delete(f"/api/privacy/user/{username}")
        assert resp_again.status_code == 404
    finally:
        _run(_cleanup(username))


def test_export_me_without_auth_is_rejected(privacy_client: TestClient) -> None:
    resp = privacy_client.get("/api/privacy/export/me")
    assert resp.status_code == 401
