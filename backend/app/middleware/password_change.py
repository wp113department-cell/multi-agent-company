"""Enforce "must change password" on the server (production audit 14, REPRO-14-006).

The seeded admin account is created with must_change_password=True, but the
flag was only returned by /api/auth/login — nothing enforced it, so the
default password could stay in use forever. While the flag is set, every API
call except the ones needed to change the password answers 403 with
reason "password_change_required".

The flag is read from the users table (15 s cache, like auth/revocation.py),
never from the token: a token claim could be dropped by /api/auth/refresh.
Plain ASGI, so streaming responses (SSE) and WebSockets pass through
untouched. Anything this check cannot decide (no/invalid token, DB down) is
passed on unchanged — the normal auth dependencies make the real decision.
"""

from __future__ import annotations

import json
import logging
import time
from http.cookies import SimpleCookie
from typing import Any, Awaitable, Callable

from app.config import get_settings

logger = logging.getLogger(__name__)

_ALLOWED = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/setup",
    "/api/auth/change-password",
}
_TTL_SECONDS = 15.0
_cache: dict[str, tuple[float, bool]] = {}

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def forget(username: str | None = None) -> None:
    """Drop the cached flag (after a password change) — or everything."""
    if username is None:
        _cache.clear()
    else:
        _cache.pop(username, None)


def _token(scope: Scope) -> str | None:
    headers = {
        k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]
    }
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    raw = headers.get("cookie")
    if raw:
        cookie: SimpleCookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return None
        morsel = cookie.get("gridiron_token")
        if morsel is not None and morsel.value:
            return morsel.value
    return None


async def _must_change(username: str) -> bool:
    now = time.monotonic()
    hit = _cache.get(username)
    if hit is not None and hit[0] > now:
        return hit[1]
    from app.db.repository import get_user
    from app.db.session import get_session_factory

    async with get_session_factory()() as db:
        user = await get_user(db, username)
    flag = bool(user is not None and user.must_change_password)
    _cache[username] = (now + _TTL_SECONDS, flag)
    return flag


class PasswordChangeRequiredMiddleware:
    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        settings = get_settings()
        if (
            not settings.jwt_auth_enabled
            or not path.startswith("/api/")
            or path.rstrip("/") in _ALLOWED
        ):
            await self.app(scope, receive, send)
            return
        token = _token(scope)
        blocked = False
        if token:
            try:
                from app.auth.jwt import decode_access_token

                username = str(decode_access_token(token).get("sub") or "")
                blocked = bool(username) and await _must_change(username)
            except Exception:
                blocked = False  # invalid token / DB down: normal auth decides
        if not blocked:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4403})
            return
        body = json.dumps(
            {
                "error": {
                    "code": "403",
                    "message": "Password change required: change your password to continue.",
                    "reason": "password_change_required",
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
