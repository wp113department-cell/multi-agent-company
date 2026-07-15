"""FastAPI dependency: extract and verify the current user from request.

When JWT_AUTH_ENABLED=true: reads Authorization: Bearer <token> header.
When JWT_AUTH_ENABLED=false: reads X-User-Role header (backward compat).

The returned CurrentUser is injected into route handlers via Depends(get_current_user).
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request
from jose import JWTError

from app.config import get_settings


@dataclass
class CurrentUser:
    username: str
    role: str       # "viewer" | "approver" | "admin"
    is_authenticated: bool = True


_ANONYMOUS = CurrentUser(username="anonymous", role="viewer", is_authenticated=False)


async def get_current_user(request: Request) -> CurrentUser:
    """Resolve the current user from request headers.

    Priority:
    1. When JWT_AUTH_ENABLED=true: Bearer token in Authorization header.
    2. Fallback: X-User-Role header (legacy, supports viewer|approver).
    3. Default: anonymous viewer.
    """
    settings = get_settings()

    if settings.jwt_auth_enabled:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
            try:
                from app.auth.jwt import decode_access_token
                payload = decode_access_token(token)
                return CurrentUser(
                    username=str(payload.get("sub", "unknown")),
                    role=str(payload.get("role", "viewer")),
                )
            except JWTError:
                raise HTTPException(status_code=401, detail="Invalid or expired token")
        raise HTTPException(status_code=401, detail="Authorization header missing or malformed")

    # Legacy fallback: X-User-Role header
    role = request.headers.get("X-User-Role", "viewer").lower()
    if role not in ("viewer", "approver", "admin"):
        role = "viewer"
    return CurrentUser(username="legacy-user", role=role, is_authenticated=False)


async def require_approver(request: Request) -> CurrentUser:
    """Dependency: require approver or admin role. 403 for viewer."""
    settings = get_settings()
    user = await get_current_user(request)

    # When RBAC is disabled, skip role check (backward compat)
    if not settings.rbac_enabled:
        return user

    if user.role not in ("approver", "admin"):
        raise HTTPException(status_code=403, detail="Approver role required")
    return user
