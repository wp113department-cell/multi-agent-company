"""Server-side check that a verified JWT still belongs to a live account.

A JWT is verified statelessly, so before this check a user who was deleted (a GDPR erasure, an
offboarding) or demoted from approver kept every privilege in their token for its whole lifetime
(24 h by default): DELETE /api/privacy/user/{name} removed the login and left the person able to
approve, push and change credentials until the token expired.

The users table is the source of truth: a token whose subject has no row is refused, and the role
used for authorisation is the row's CURRENT role, not the one frozen into the token. The answer is
cached for a few seconds so this costs one small query per user per interval, not per request.
"""

from __future__ import annotations

import time

from app.config import get_settings

_TTL_SECONDS = 15.0
_cache: dict[str, tuple[float, str | None]] = {}


def invalidate(username: str | None = None) -> None:
    """Forget a cached answer (all of them when username is None) — call after changing or
    deleting an account so the change is effective immediately, not after the TTL."""
    if username is None:
        _cache.clear()
    else:
        _cache.pop(username, None)


async def current_role(
    username: str, claimed_role: str, db: object | None = None
) -> str | None:
    """The role this account holds right now, or None if the account no longer exists."""
    if not get_settings().jwt_revalidate_against_db:
        return claimed_role
    now = time.monotonic()
    hit = _cache.get(username)
    if hit is not None and hit[0] > now:
        return hit[1]

    from app.db.repository import get_user

    if db is not None:
        user = await get_user(db, username)  # type: ignore[arg-type]
    else:
        from app.db.session import get_session_factory

        async with get_session_factory()() as session:
            user = await get_user(session, username)
    role = str(user.role) if user is not None else None
    _cache[username] = (now + _TTL_SECONDS, role)
    return role
