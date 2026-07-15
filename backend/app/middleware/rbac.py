"""RBAC — viewer vs approver role enforcement.

The server is the enforcement point. UI hiding buttons is a courtesy only.

Role lookup (in priority order):
  1. When JWT_AUTH_ENABLED=true: Authorization: Bearer <token> → role from JWT claim.
  2. X-User-Role header: "approver" is accepted directly (legacy/dev mode).
  3. X-User-Id header → user_roles table → role (original Phase 5 path).
  4. Default: "viewer".

When RBAC_ENABLED=false all requests are treated as "approver" (local dev).
"""
from __future__ import annotations

import logging

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.db.models import UserRole

logger = logging.getLogger(__name__)


async def _get_user_role(user_id: str, db: AsyncSession) -> str:
    result = await db.execute(select(UserRole).where(UserRole.user_id == user_id))
    row = result.scalar_one_or_none()
    return row.role if row else "viewer"


async def require_approver(
    request: Request,
    x_user_id: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> str:
    """FastAPI dependency — raise 403 if the caller is not an approver.

    Returns the resolved user_id / username so route handlers can log it.

    Auth priority (highest first):
      1. JWT Bearer token in Authorization header (when JWT_AUTH_ENABLED=true)
      2. X-User-Role: approver header (dev / legacy shortcut)
      3. X-User-Id header → DB user_roles lookup
    """
    settings = get_settings()

    if not settings.rbac_enabled:
        return x_user_id or "system"

    # 1. JWT path — takes precedence when enabled
    if settings.jwt_auth_enabled:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
            try:
                from app.auth.jwt import decode_access_token
                payload = decode_access_token(token)
                role = str(payload.get("role", "viewer"))
                username = str(payload.get("sub", "unknown"))
                if role not in ("approver", "admin"):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"User {username!r} has role {role!r}; approver required",
                    )
                return username
            except Exception as exc:
                if isinstance(exc, HTTPException):
                    raise
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization: Bearer <token> header required when JWT auth is enabled",
        )

    # 2. X-User-Role shortcut — read from request headers (avoids Header sentinel issue)
    x_user_role = request.headers.get("X-User-Role", "")
    if x_user_role.lower() in ("approver", "admin"):
        return x_user_id or x_user_role

    # 3. X-User-Id → DB lookup
    if x_user_id:
        role = await _get_user_role(x_user_id, db)
        if role not in ("approver", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User {x_user_id!r} has role {role!r}; approver required",
            )
        return x_user_id

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Approver role required: provide Authorization: Bearer <token> or X-User-Role: approver header",
    )
