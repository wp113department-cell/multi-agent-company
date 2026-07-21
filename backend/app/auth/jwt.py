"""JWT token creation and verification.

Uses python-jose for signing and bcrypt directly for password hashing.
All configuration reads from Settings — no literals in this module.

When JWT_AUTH_ENABLED=false (default), the RBAC middleware falls back to
the legacy X-User-Role header so existing integrations keep working.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict[str, Any]) -> str:
    """Sign and return a JWT access token."""
    settings = get_settings()
    if not settings.jwt_secret_key:
        raise ValueError("JWT_SECRET_KEY must be set when JWT_AUTH_ENABLED=true")

    payload = dict(data)
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload["exp"] = expire
    payload["iat"] = datetime.now(timezone.utc)
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT access token. Raises JWTError on invalid/expired tokens."""
    settings = get_settings()
    if not settings.jwt_secret_key:
        raise JWTError("JWT_SECRET_KEY is not configured")
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    return payload
