"""Auth API — JWT login and token endpoints.

Routes:
  POST /api/auth/login     → exchange username+password for a JWT
  GET  /api/auth/me        → return the current user's identity from their token
  POST /api/auth/refresh   → renew an already-valid session's JWT and cookie

AUDIT_Q_BATCH14 §48 gap-closure (2026-08-12) — credentials are now stored in
a real, normalized `users` table (migration 044), replacing the Phase-1
shortcut this module's docstring used to describe (a JSON array inside a
single system_settings row). See app/db/models.py's User model docstring
for the cutover details.

When JWT_AUTH_ENABLED=false, login still works but the token is optional
for all other endpoints (backward compat with X-User-Role header).

login and setup are deliberately rate-limited far below rate_limit_default
(Settings.rate_limit_login) since they are the only unauthenticated,
credential-checking endpoints in the API — the natural target for brute
force / credential stuffing.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentUser, get_current_user
from app.auth.jwt import create_access_token, verify_password
from app.config import get_settings
from app.db import get_db
from app.db.repository import count_users, create_user, get_user, update_user_password
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token_type: str = "bearer"
    role: str
    username: str
    must_change_password: bool = False


class MeResponse(BaseModel):
    username: str
    role: str
    is_authenticated: bool


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/login", response_model=LoginResponse)
@limiter.limit(get_settings().rate_limit_login)
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Exchange username + password for a signed JWT access token.

    Credentials are stored in the real `users` table (migration 044).

    Create the first user via: POST /api/auth/setup (see below).
    """
    settings = get_settings()
    if not settings.jwt_secret_key:
        raise HTTPException(
            status_code=501,
            detail="JWT auth is not configured. Set JWT_SECRET_KEY and JWT_AUTH_ENABLED=true.",
        )

    try:
        user = await get_user(db, body.username)
    except Exception as exc:
        from app.db.errors import is_db_unavailable

        if is_db_unavailable(exc):  # audit 13: an outage is not a config error
            logger.error("Login: database unavailable: %r", exc)
            raise HTTPException(
                status_code=503, detail="Database unavailable, retry shortly"
            ) from exc
        logger.exception("Failed to load user %s from users table", body.username)
        raise HTTPException(status_code=500, detail="Auth configuration error") from exc

    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    role = user.role
    token = create_access_token({"sub": body.username, "role": role})
    response.set_cookie(
        key="gridiron_token",
        value=token,
        max_age=settings.jwt_access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.deployment_env in ("staging", "production"),
        samesite="lax",
        path="/",
    )
    return LoginResponse(
        role=role,
        username=body.username,
        must_change_password=user.must_change_password,
    )


@router.get("/me", response_model=MeResponse)
async def me(current_user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    """Return the identity of the currently authenticated user."""
    return MeResponse(
        username=current_user.username,
        role=current_user.role,
        is_authenticated=current_user.is_authenticated,
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    response: Response,
    current_user: CurrentUser = Depends(get_current_user),
) -> LoginResponse:
    """Renew the caller's session: issues a fresh JWT (full expiry window) for
    an already-valid, unexpired session and resets the httponly cookie.

    Requires a real, currently-valid JWT — get_current_user() only sets
    is_authenticated=True for a verified token (never for the legacy
    X-User-Role header, and never for an expired/invalid one), so a caller
    whose session already lapsed must log in again rather than refresh.
    """
    if not current_user.is_authenticated:
        raise HTTPException(
            status_code=401,
            detail="A valid session is required to refresh (log in again).",
        )

    settings = get_settings()
    token = create_access_token(
        {"sub": current_user.username, "role": current_user.role}
    )
    response.set_cookie(
        key="gridiron_token",
        value=token,
        max_age=settings.jwt_access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.deployment_env in ("staging", "production"),
        samesite="lax",
        path="/",
    )
    return LoginResponse(role=current_user.role, username=current_user.username)


@router.post("/setup")
@limiter.limit(get_settings().rate_limit_login)
async def setup_first_user(
    request: Request,
    body: LoginRequest,
    role: str = "approver",
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Create the first admin user when the users table is empty.

    Once any user exists, this endpoint returns 409. Use the DB directly to manage
    additional users.
    """
    settings = get_settings()
    if settings.deployment_env == "production":
        raise HTTPException(status_code=404, detail="Not found")
    if not settings.jwt_secret_key:
        raise HTTPException(
            status_code=501, detail="JWT_SECRET_KEY must be set to use auth."
        )

    from app.auth.jwt import hash_password

    if await count_users(db) > 0:
        raise HTTPException(
            status_code=409,
            detail="Auth users already configured. Use the DB to manage users.",
        )

    if role not in ("viewer", "approver", "admin"):
        raise HTTPException(
            status_code=400, detail="role must be viewer | approver | admin"
        )

    await create_user(db, body.username, hash_password(body.password), role=role)
    logger.info("First auth user created: %s (role=%s)", body.username, role)
    return {"status": "created", "username": body.username, "role": role}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> Response:
    """Clear the browser session cookie without exposing it to JavaScript.

    Production audit 12: this used to return FastAPI's injected `response`
    parameter itself. That object is only a header/cookie carrier with
    status_code=None — returning it made uvicorn fail to send it, so every
    real logout was a 500 and the httpOnly cookie was never cleared.
    """
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(key="gridiron_token", path="/")
    return response


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Gap-closure (Audit 05 fix, SEC-05-015): the only way to durably change
    a user's (including the seeded admin's) password used to be overriding
    an env var before every restart — any change made another way was
    silently reverted. This is the real, durable change path: requires the
    caller to be authenticated (a real JWT, not the legacy header — a
    CurrentUser from the X-User-Role fallback or anonymous default has
    is_authenticated=False) and to know their current password, then
    persists the new hash and clears must_change_password."""
    if not current_user.is_authenticated:
        raise HTTPException(
            status_code=401,
            detail="A real JWT is required to change a password "
            "(the legacy X-User-Role header cannot be used here).",
        )

    from app.auth.jwt import hash_password

    user = await get_user(db, current_user.username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    if not body.new_password or len(body.new_password) < 8:
        raise HTTPException(
            status_code=400, detail="New password must be at least 8 characters"
        )

    await update_user_password(
        db, current_user.username, hash_password(body.new_password)
    )
    logger.info("Password changed for user: %s", current_user.username)
    from app.middleware.password_change import forget

    forget(
        current_user.username
    )  # the API unlocks immediately, not after the cache TTL
    return {"status": "changed", "username": current_user.username}
