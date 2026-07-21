"""Auth API — JWT login and token endpoints.

Routes:
  POST /api/auth/login     → exchange username+password for a JWT
  GET  /api/auth/me        → return the current user's identity from their token
  POST /api/auth/refresh   → stub (not yet implemented — return 501)

For Phase 1, credentials are stored in the system_settings table
(key="auth_users", value=JSON list of {username, hashed_password, role}).
This avoids adding a users table before full RBAC is needed.

When JWT_AUTH_ENABLED=false, login still works but the token is optional
for all other endpoints (backward compat with X-User-Role header).
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.auth.jwt import create_access_token, verify_password
from app.config import get_settings
from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class MeResponse(BaseModel):
    username: str
    role: str
    is_authenticated: bool


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest, db: AsyncSession = Depends(get_db)
) -> LoginResponse:
    """Exchange username + password for a signed JWT access token.

    Credentials are stored in system_settings.key='auth_users' as a JSON array:
    [{"username": "alice", "hashed_password": "<bcrypt>", "role": "approver"}, ...]

    Create the first user via: POST /api/auth/setup (see below).
    """
    settings = get_settings()
    if not settings.jwt_secret_key:
        raise HTTPException(
            status_code=501,
            detail="JWT auth is not configured. Set JWT_SECRET_KEY and JWT_AUTH_ENABLED=true.",
        )

    # Load credentials from DB settings table
    try:
        from sqlalchemy import text

        row = await db.execute(
            text("SELECT value FROM system_settings WHERE key = 'auth_users'")
        )
        result = row.scalar_one_or_none()
        users: list[dict[str, str]] = json.loads(result) if result else []
    except Exception as exc:
        logger.exception("Failed to load auth_users from system_settings")
        raise HTTPException(status_code=500, detail="Auth configuration error") from exc

    # Find matching user
    user = next((u for u in users if u.get("username") == body.username), None)
    if user is None or not verify_password(
        body.password, user.get("hashed_password", "")
    ):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    role = user.get("role", "viewer")
    token = create_access_token({"sub": body.username, "role": role})
    return LoginResponse(access_token=token, role=role, username=body.username)


@router.get("/me", response_model=MeResponse)
async def me(current_user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    """Return the identity of the currently authenticated user."""
    return MeResponse(
        username=current_user.username,
        role=current_user.role,
        is_authenticated=current_user.is_authenticated,
    )


@router.post("/setup")
async def setup_first_user(
    body: LoginRequest,
    role: str = "approver",
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Create the first admin user when auth_users list is empty.

    Once any user exists, this endpoint returns 409. Use the DB directly to manage
    additional users.
    """
    settings = get_settings()
    if not settings.jwt_secret_key:
        raise HTTPException(
            status_code=501, detail="JWT_SECRET_KEY must be set to use auth."
        )

    from app.auth.jwt import hash_password
    from sqlalchemy import text

    # Load existing users
    row = await db.execute(
        text("SELECT value FROM system_settings WHERE key = 'auth_users'")
    )
    result = row.scalar_one_or_none()
    existing: list[dict[str, str]] = json.loads(result) if result else []

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Auth users already configured. Use the DB to manage users.",
        )

    if role not in ("viewer", "approver", "admin"):
        raise HTTPException(
            status_code=400, detail="role must be viewer | approver | admin"
        )

    new_user = {
        "username": body.username,
        "hashed_password": hash_password(body.password),
        "role": role,
    }
    users_json = json.dumps([new_user])

    await db.execute(
        text(
            "INSERT INTO system_settings (key, value) VALUES ('auth_users', :v) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"v": users_json},
    )
    await db.commit()
    logger.info("First auth user created: %s (role=%s)", body.username, role)
    return {"status": "created", "username": body.username, "role": role}
