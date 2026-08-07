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
        cached = await get_cached_response(db, request, "push_task")
        if cached is not None:
            return cached
        ...
        result = {...}
        await store_response(db, request, "push_task", result)
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


async def get_cached_response(
    db: AsyncSession, request: Request, endpoint: str
) -> dict[str, Any] | None:
    """Returns the previously stored response for this Idempotency-Key +
    endpoint, or None if no key was sent, none is stored yet, or a stored
    key's request body hash doesn't match this request (a reused key with a
    genuinely different payload — surfaced as a fresh call rather than a
    silently wrong cached response)."""
    key = request.headers.get(_HEADER_NAME)
    if not key:
        return None
    body = await request.body()
    row = await db.get(IdempotencyKey, (key, endpoint))
    if row is None:
        return None
    if row.request_hash != _request_hash(body):
        logger.warning(
            "Idempotency-Key %r reused on %s with a different request body — "
            "not returning the stale cached response",
            key,
            endpoint,
        )
        return None
    logger.info("Idempotency-Key %r on %s — returning cached response", key, endpoint)
    result: dict[str, Any] = json.loads(row.response_body)
    return result


async def store_response(
    db: AsyncSession, request: Request, endpoint: str, response: dict[str, Any]
) -> None:
    """Persists this request's response under its Idempotency-Key, if one was
    sent. Safe to call unconditionally — a no-op when the client sent no
    key."""
    key = request.headers.get(_HEADER_NAME)
    if not key:
        return
    body = await request.body()
    db.add(
        IdempotencyKey(
            key=key,
            endpoint=endpoint,
            request_hash=_request_hash(body),
            response_status=200,
            response_body=json.dumps(response, default=str),
        )
    )
    try:
        await db.commit()
    except Exception:
        # A concurrent duplicate request racing to insert the same
        # (key, endpoint) primary key — the other one already stored the
        # canonical response; this request's own real result is still
        # returned to its caller, just not persisted a second time.
        # Non-fatal by design, matching this codebase's established
        # convention that a dedup/audit side-record never blocks the real
        # operation it's recording.
        await db.rollback()
        logger.debug(
            "Idempotency-Key %r store on %s skipped (likely concurrent duplicate)",
            key,
            endpoint,
        )


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
