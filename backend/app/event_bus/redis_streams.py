"""Redis Streams Event Bus adapter.

Publishes GridironEvents to a Redis Stream ("gridiron:events") in addition to
the in-process Postgres LISTEN/NOTIFY bus. Consumer groups allow multiple
workers to process events with at-least-once delivery.

When `redis_streams_enabled=False` (default), every function is a safe no-op.

Stream key layout:
  gridiron:events      — main event stream
  Consumer group:      — REDIS_CONSUMER_GROUP (default: "gridiron-consumers")

Message fields:
  event_id, event_type, task_id, epic_id, payload (JSON), emitted_by, created_at
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.event_bus.models import GridironEvent

logger = logging.getLogger(__name__)

_STREAM_KEY = "gridiron:events"
_MAXLEN = 10_000  # keep at most 10 k events in the stream (approximate trimming)

_redis_client: Any = None
_group_created: bool = False


def _get_client() -> Any:
    """Lazy-init Redis client using config redis_url."""
    global _redis_client
    if _redis_client is None:
        from app.config import get_settings
        import redis

        settings = get_settings()
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _ensure_group() -> None:
    """Create the consumer group once per process."""
    global _group_created
    if _group_created:
        return
    from app.config import get_settings

    settings = get_settings()
    client = _get_client()
    try:
        client.xgroup_create(
            _STREAM_KEY,
            settings.redis_consumer_group,
            id="$",
            mkstream=True,
        )
        logger.info("Redis Streams consumer group '%s' created", settings.redis_consumer_group)
    except Exception as exc:
        if "BUSYGROUP" in str(exc):
            pass  # Group already exists — OK
        else:
            logger.warning("Could not create Redis Streams consumer group: %s", exc)
    _group_created = True


def publish_to_stream(event: GridironEvent) -> None:
    """Publish event to Redis Stream. No-op when redis_streams_enabled=False."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.redis_streams_enabled:
        return

    try:
        _ensure_group()
        client = _get_client()
        payload: dict[str, str] = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "task_id": str(event.task_id) if event.task_id is not None else "",
            "epic_id": str(event.epic_id) if event.epic_id is not None else "",
            "payload": json.dumps(event.payload),
            "emitted_by": event.emitted_by,
            "created_at": (event.created_at or datetime.now(timezone.utc)).isoformat(),
        }
        msg_id: str = client.xadd(_STREAM_KEY, payload, maxlen=_MAXLEN, approximate=True)
        logger.debug("Published %s to Redis Streams msg_id=%s", event.event_type, msg_id)
    except Exception:
        logger.exception("Failed to publish event %s to Redis Streams", event.event_id)


def read_pending(
    consumer_name: str,
    count: int = 10,
    block_ms: int = 1000,
) -> list[dict[str, Any]]:
    """Read up to `count` unacknowledged messages from the stream.

    Returns a list of dicts with `msg_id` and `data` keys.
    No-op (returns []) when redis_streams_enabled=False.
    """
    from app.config import get_settings

    settings = get_settings()
    if not settings.redis_streams_enabled:
        return []

    try:
        _ensure_group()
        client = _get_client()
        raw = client.xreadgroup(
            settings.redis_consumer_group,
            consumer_name,
            {_STREAM_KEY: ">"},
            count=count,
            block=block_ms,
        )
        if not raw:
            return []

        results: list[dict[str, Any]] = []
        for _stream, messages in raw:
            for msg_id, data in messages:
                results.append({"msg_id": msg_id, "data": data})
        return results
    except Exception:
        logger.exception("Failed to read from Redis Streams")
        return []


def acknowledge(msg_id: str) -> None:
    """Acknowledge a message in the consumer group."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.redis_streams_enabled:
        return
    try:
        client = _get_client()
        client.xack(_STREAM_KEY, settings.redis_consumer_group, msg_id)
    except Exception:
        logger.exception("Failed to ack Redis Streams msg_id=%s", msg_id)


def stream_length() -> int:
    """Return current stream length. Returns 0 when disabled or on error."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.redis_streams_enabled:
        return 0
    try:
        return int(_get_client().xlen(_STREAM_KEY))
    except Exception:
        return 0


def reset_client() -> None:
    """Reset cached Redis client (used in tests)."""
    global _redis_client, _group_created
    _redis_client = None
    _group_created = False
