"""
Event Bus — Postgres LISTEN/NOTIFY transport with in-memory subscriber registry.

Architecture:
- Subscribers register handlers per event_type via subscribe().
- publish_event() dispatches to all registered handlers in-process (sync/async).
- When a DB session is available, events are also persisted to the events table
  and a NOTIFY is sent on channel "gridiron_events".
- Consumer failure triggers retry (up to 3×) then writes to failed_events.
- get_unprocessed_events() supports replay on restart.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from app.event_bus.models import GridironEvent

logger = logging.getLogger(__name__)

# event_type → list of async handler functions
_subscribers: dict[str, list[Callable[[GridironEvent], Awaitable[None] | None]]] = defaultdict(list)

_MAX_RETRIES = 3


def subscribe(
    event_type: str,
    handler: Callable[[GridironEvent], Awaitable[None] | None],
) -> None:
    """Register a handler for an event type. Idempotent if the exact handler is already registered."""
    if handler not in _subscribers[event_type]:
        _subscribers[event_type].append(handler)
        logger.debug("Subscribed %s to event_type=%s", handler.__name__, event_type)


def unsubscribe(event_type: str, handler: Callable[[GridironEvent], Awaitable[None] | None]) -> None:
    """Remove a handler from an event type."""
    try:
        _subscribers[event_type].remove(handler)
    except ValueError:
        pass


async def _dispatch_to_handler(
    event: GridironEvent,
    handler: Callable[[GridironEvent], Awaitable[None] | None],
) -> bool:
    """Dispatch event to one handler. Returns True on success."""
    for attempt in range(_MAX_RETRIES):
        try:
            result = handler(event)
            if asyncio.iscoroutine(result):
                await result
            return True
        except Exception as e:
            logger.warning(
                "Handler %s failed for event %s (attempt %d/%d): %s",
                handler.__name__, event.event_type, attempt + 1, _MAX_RETRIES, e,
            )
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(0.5 * (2 ** attempt))
    return False


async def _persist_event(event: GridironEvent, db: Any) -> None:
    """Persist event to DB events table. No-op if db is None."""
    if db is None:
        return
    try:
        from sqlalchemy import text
        await db.execute(
            text(
                "INSERT INTO events (event_id, event_type, task_id, epic_id, payload, emitted_by, created_at) "
                "VALUES (:eid, :etype, :tid, :epic_id, :payload, :emitted_by, :created_at)"
            ),
            {
                "eid": event.event_id,
                "etype": event.event_type,
                "tid": event.task_id,
                "epic_id": event.epic_id,
                "payload": json.dumps(event.payload),
                "emitted_by": event.emitted_by,
                "created_at": event.created_at,
            },
        )
        await db.execute(
            text("SELECT pg_notify('gridiron_events', :payload)"),
            {"payload": json.dumps({"event_id": event.event_id, "event_type": event.event_type})},
        )
        await db.commit()
    except Exception:
        logger.exception("Failed to persist event %s", event.event_id)


async def _write_failed_event(event: GridironEvent, handler_name: str, error: str, db: Any) -> None:
    """Write to failed_events table after all retries exhausted."""
    if db is None:
        logger.error("FAILED EVENT (no DB) event_id=%s handler=%s error=%s", event.event_id, handler_name, error)
        return
    try:
        from sqlalchemy import text
        await db.execute(
            text(
                "INSERT INTO failed_events (event_id, event_type, task_id, payload, emitted_by, "
                "handler_name, error, failed_at) VALUES "
                "(:eid, :etype, :tid, :payload, :emitted_by, :handler_name, :error, :failed_at)"
            ),
            {
                "eid": event.event_id,
                "etype": event.event_type,
                "tid": event.task_id,
                "payload": json.dumps(event.payload),
                "emitted_by": event.emitted_by,
                "handler_name": handler_name,
                "error": error,
                "failed_at": datetime.now(timezone.utc),
            },
        )
        await db.commit()
    except Exception:
        logger.exception("Failed to write failed_event for %s", event.event_id)


async def publish_event(event: GridironEvent, db: Any = None) -> None:
    """
    Publish an event to all registered subscribers.

    - Dispatches to in-process handlers (with retry).
    - Persists to DB events table if db is provided.
    - Writes to failed_events if a handler exhausts retries.
    - Events are ordered per task_id (sequential publish within a task pipeline).
    """
    logger.info("EVENT %s task_id=%s emitted_by=%s", event.event_type, event.task_id, event.emitted_by)

    # Persist first so the event is recorded even if handlers fail
    await _persist_event(event, db)

    handlers = list(_subscribers.get(event.event_type, []))
    for handler in handlers:
        success = await _dispatch_to_handler(event, handler)
        if not success:
            await _write_failed_event(event, handler.__name__, "max retries exceeded", db)


async def get_unprocessed_events(
    task_id: str,
    since: datetime,
    db: Any,
) -> list[GridironEvent]:
    """
    Replay: return events for task_id with created_at > since.
    Used by consumers on restart to process unhandled events.
    """
    if db is None:
        return []
    try:
        from sqlalchemy import text
        rows = await db.execute(
            text(
                "SELECT event_id, event_type, task_id, epic_id, payload, emitted_by, created_at "
                "FROM events WHERE task_id = :tid AND created_at > :since ORDER BY created_at ASC"
            ),
            {"tid": task_id, "since": since},
        )
        result = rows.mappings().all()
        return [
            GridironEvent(
                event_id=str(r["event_id"]),
                event_type=str(r["event_type"]),
                task_id=str(r["task_id"]) if r["task_id"] else None,
                epic_id=str(r["epic_id"]) if r.get("epic_id") else None,
                payload=r["payload"] if isinstance(r["payload"], dict) else json.loads(r["payload"]),
                emitted_by=str(r["emitted_by"]),
                created_at=r["created_at"],
            )
            for r in result
        ]
    except Exception:
        logger.exception("Failed to fetch unprocessed events for task %s", task_id)
        return []
