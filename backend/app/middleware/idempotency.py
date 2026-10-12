"""Generic Idempotency-Key support — AUDIT_Q_BATCH08 §66 "Idempotency".

Generalizes the narrow, state-based guard already established for
approve_task() (HTTP 409 if already coded) into a reusable primitive for any
mutating endpoint where a client retry (e.g. after a timeout on a request
that had already succeeded) risks a real, visible duplicate side effect —
the same "write_remote ... blindly retrying risks a second PR/push" hazard
class app/agents/base_graph.py's `_RETRY_EXCLUDED_PERMISSIONS` already
documents at the tool-retry layer, now closed at the HTTP layer too.

Opt-in per endpoint, not blanket ASGI middleware — a global rewrite of every
response path (including SSE streams) would be a far riskier change than
this finding warrants:

    @router.post("/{task_id}/push")
    async def push_task(
        task_id: int,
        request: Request,
        db: AsyncSession = Depends(get_db),
        ...
    ) -> dict[str, Any]:
        cached = await get_cached_response(db, request, "push_task", actor)
        if cached is not None:
            return cached
        try:
            ...
            result = {...}
        except BaseException:
            await release_reservation(db, request, "push_task", actor)
            raise
        await store_response(db, request, "push_task", result, actor)
        return result

No Idempotency-Key header sent -> both calls are no-ops -> zero behavior
change for any existing caller that doesn't send one.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import IdempotencyKey

logger = logging.getLogger(__name__)

_HEADER_NAME = "Idempotency-Key"


def _request_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


_IN_PROGRESS = 0


def _scope(endpoint: str, actor: str | None) -> str:
    """Sol A23: a key is scoped to the person using it, so two users' keys
    can never replay each other's responses."""
    return f"{endpoint}|{actor}" if actor else endpoint


async def get_cached_response(
    db: AsyncSession, request: Request, endpoint: str, actor: str | None = None
) -> dict[str, Any] | None:
    """Reserve this request's Idempotency-Key, or return the stored answer.

    Sol A23 (2026-10-12): the key used to be checked before the work and
    stored after it, so two identical requests arriving together both did
    the work. Now the key is reserved atomically first (INSERT ... ON
    CONFLICT DO NOTHING on the primary key):
      - first request: reserved, returns None, the caller does the work and
        then calls store_response() (or release_reservation() on failure);
      - same key and body, finished: the stored response is returned;
      - same key and body, still running: 409 "already in progress";
      - same key, different body: 409 (a reused key never runs a new call).
    No header -> None and nothing is stored, exactly as before.
    """
    from fastapi import HTTPException
    from sqlalchemy.dialects.postgresql import insert

    key = request.headers.get(_HEADER_NAME)
    if not key:
        return None
    scope = _scope(endpoint, actor)
    digest = _request_hash(await request.body())
    reserved = await db.execute(
        insert(IdempotencyKey)
        .values(
            key=key,
            endpoint=scope,
            request_hash=digest,
            response_status=_IN_PROGRESS,
            response_body="",
        )
        .on_conflict_do_nothing(index_elements=["key", "endpoint"])
        .returning(IdempotencyKey.key)
    )
    if reserved.first() is not None:
        await db.commit()
        return None
    await db.rollback()
    row = await db.get(IdempotencyKey, (key, scope), populate_existing=True)
    if row is None:  # released between the insert and this read
        return await get_cached_response(db, request, endpoint, actor)
    if row.request_hash != digest:
        raise HTTPException(
            status_code=409,
            detail="This Idempotency-Key was already used for a different request.",
        )
    if row.response_status == _IN_PROGRESS:
        raise HTTPException(
            status_code=409,
            detail="The same request is already being processed; try again shortly.",
        )
    logger.info("Idempotency-Key %r on %s — returning cached response", key, endpoint)
    result: dict[str, Any] = json.loads(row.response_body)
    return result


async def store_response(
    db: AsyncSession,
    request: Request,
    endpoint: str,
    response: dict[str, Any],
    actor: str | None = None,
) -> None:
    """Record the finished response for a reserved key (no-op without one)."""
    from sqlalchemy import update

    key = request.headers.get(_HEADER_NAME)
    if not key:
        return
    await db.execute(
        update(IdempotencyKey)
        .where(
            IdempotencyKey.key == key,
            IdempotencyKey.endpoint == _scope(endpoint, actor),
        )
        .values(response_status=200, response_body=json.dumps(response, default=str))
    )
    await db.commit()


async def release_reservation(
    db: AsyncSession, request: Request, endpoint: str, actor: str | None = None
) -> None:
    """The work failed: free the key so a retry can run (no-op without one)."""
    key = request.headers.get(_HEADER_NAME)
    if not key:
        return
    try:
        await db.rollback()
        await db.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.key == key,
                IdempotencyKey.endpoint == _scope(endpoint, actor),
                IdempotencyKey.response_status == _IN_PROGRESS,
            )
        )
        await db.commit()
    except Exception:
        logger.warning("Could not release Idempotency-Key %r", key, exc_info=True)


async def purge_expired_idempotency_keys(db: AsyncSession) -> int:
    """Deletes idempotency records older than idempotency_key_ttl_seconds.
    Called from app/services/retention.py's own cleanup cycle rather than a
    new scheduling mechanism."""
    ttl = get_settings().idempotency_key_ttl_seconds
    if ttl <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl)
    result = await db.execute(
        delete(IdempotencyKey).where(IdempotencyKey.created_at < cutoff)
    )
    await db.commit()
    return getattr(result, "rowcount", 0)
