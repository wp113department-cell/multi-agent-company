"""RBAC — viewer vs approver role enforcement.

The server is the enforcement point. UI hiding buttons is a courtesy only.

Role lookup: X-User-Id header → user_roles table → role.
Missing header or missing row → defaults to "viewer".
When RBAC_ENABLED=false (tests / local dev without auth) all requests are treated as "approver".
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.db.models import UserRole


async def _get_user_role(user_id: str, db: AsyncSession) -> str:
    result = await db.execute(select(UserRole).where(UserRole.user_id == user_id))
    row = result.scalar_one_or_none()
    return row.role if row else "viewer"


async def require_approver(
    x_user_id: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> str:
    """FastAPI dependency — raise 403 if the caller is not an approver.

    Returns the resolved user_id so route handlers can log it.
    """
    settings = get_settings()

    if not settings.rbac_enabled:
        return x_user_id or "system"

    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="X-User-Id header required",
        )

    role = await _get_user_role(x_user_id, db)
    if role != "approver":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User {x_user_id!r} has role {role!r}; approver required",
        )
    return x_user_id
