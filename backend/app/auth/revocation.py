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
_cache: dict[str, tuple[float, tuple[str, int] | None]] = {}


def invalidate(username: str | None = None) -> None:
    """Forget a cached answer (all of them when username is None) — call after changing or
    deleting an account so the change is effective immediately, not after the TTL."""
    if username is None:
        _cache.clear()
    else:
        _cache.pop(username, None)


async def current_role(
    username: str,
    claimed_role: str,
    db: object | None = None,
    token_version: int | None = None,
) -> str | None:
    """The role this account holds right now, or None if the account no
    longer exists — or (Sol A12) if `token_version` (the token's "tv"; a
    token without one counts as 0) differs from the account's: the user has
    signed out or changed the password since that token was issued."""
    if not get_settings().jwt_revalidate_against_db:
        return claimed_role
    now = time.monotonic()
    hit = _cache.get(username)
    if hit is None or hit[0] <= now:
        from app.db.repository import get_user

        if db is not None:
            user = await get_user(db, username)  # type: ignore[arg-type]
        else:
            from app.db.session import get_session_factory

            async with get_session_factory()() as session:
                user = await get_user(session, username)
        account = (
            (str(user.role), int(getattr(user, "token_version", 0) or 0))
            if user is not None
            else None
        )
        hit = (now + _TTL_SECONDS, account)
        _cache[username] = hit
    account = hit[1]
    if account is None:
        return None
    role, version = account
    if int(token_version or 0) != version:
        return None
    return role
