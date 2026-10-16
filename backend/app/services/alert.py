"""AlertService — fires webhook notifications on notable task events.

Called by API handlers when a task transitions to 'blocked' or 'failed'.
Falls back silently when ALERT_WEBHOOK_URL is not configured.

Sol A43 (2026-10-16): an alert used to be one POST — if the receiving
service was down it was lost. Now it is stored in the alert_outbox table
first, sent at once, and retried by deliver_due_alerts() (a leader loop in
app/main.py) with growing waits until it is delivered or, after
ALERT_MAX_ATTEMPTS, kept as a dead letter (logged as an error). Every
attempt carries the same X-Gridiron-Event-Id so the receiver can drop
repeats; with ALERT_WEBHOOK_SECRET set it is signed (X-Gridiron-Signature)
over X-Gridiron-Timestamp and the body, so the receiver can check where it
came from and refuse old, replayed ones. If the database cannot be reached
the alert is still sent once, as before.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

logger = logging.getLogger(__name__)

_RETRY_BASE_SECONDS = 30
_RETRY_MAX_SECONDS = 3600
_KEEP_SENT_DAYS = 30


def _retry_delay(attempts: int) -> timedelta:
    """30 s, 1 min, 2 min, … capped at 1 hour."""
    return timedelta(
        seconds=min(_RETRY_BASE_SECONDS * 2 ** max(attempts - 1, 0), _RETRY_MAX_SECONDS)
    )


def sign_alert(secret: str, timestamp: str, body: bytes) -> str:
    """The X-Gridiron-Signature value a receiver recomputes to check an alert."""
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


async def _deliver(payload: dict[str, object], event_id: str) -> str | None:
    """One POST attempt. Returns None when delivered, else the error."""
    settings = get_settings()
    body = json.dumps(payload, default=str).encode()
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-Gridiron-Event-Id": event_id,
        "X-Gridiron-Timestamp": timestamp,
    }
    if settings.alert_webhook_secret:
        headers["X-Gridiron-Signature"] = sign_alert(
            settings.alert_webhook_secret, timestamp, body
        )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                settings.alert_webhook_url, content=body, headers=headers
            )
        if resp.status_code >= 400:
            return f"HTTP {resp.status_code}"
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"[:500]


def _dedup_key(payload: dict[str, object]) -> str:
    """The same alert (ignoring when it was raised) is queued only once
    while it is still undelivered."""
    same = {k: v for k, v in payload.items() if k != "timestamp"}
    return hashlib.sha256(
        json.dumps(same, sort_keys=True, default=str).encode()
    ).hexdigest()


async def _record_attempt(
    db: AsyncSession, row_id: int, attempts: int, error: str | None
) -> None:
    from sqlalchemy import update

    from app.db.models import AlertOutbox

    now = datetime.now(timezone.utc)
    if error is None:
        values: dict[str, object] = {
            "status": "sent",
            "sent_at": now,
            "attempts": attempts,
        }
    elif attempts >= get_settings().alert_max_attempts:
        values = {"status": "dead", "attempts": attempts, "last_error": error}
    else:
        values = {
            "attempts": attempts,
            "last_error": error,
            "next_attempt_at": now + _retry_delay(attempts),
        }
    await db.execute(
        update(AlertOutbox).where(AlertOutbox.id == row_id).values(**values)
    )
    if values.get("status") == "dead":
        logger.error(
            "Alert %s was not delivered after %d attempts and is kept as a dead "
            "letter (table alert_outbox): %s",
            row_id,
            attempts,
            error,
        )


async def _post_alert(payload: dict[str, object], log_ctx: str) -> None:
    """Store the alert in the outbox, then try to send it at once. Never
    raises — failures are only logged and retried by deliver_due_alerts()."""
    from app.observability.redaction import redact

    payload = redact(payload)  # Sol A13/G10: alerts carry no secrets
    dedup_key = _dedup_key(payload)
    event_id = str(uuid.uuid4())
    payload["event_id"] = event_id
    row_id: int | None = None
    engine = None
    try:
        from sqlalchemy.dialects.postgresql import insert

        from app.db.models import AlertOutbox
        from app.db.session import new_isolated_async_engine

        # Callers run on the main loop, in worker threads and in RQ jobs; a
        # short-lived engine is never tied to another event loop.
        engine = new_isolated_async_engine()
        async with AsyncSession(engine, expire_on_commit=False) as db:
            row_id = (
                await db.execute(
                    insert(AlertOutbox)
                    .values(
                        event_id=event_id,
                        dedup_key=dedup_key,
                        payload=payload,
                        status="pending",
                        attempts=0,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["dedup_key"],
                        index_where=AlertOutbox.status == "pending",
                    )
                    .returning(AlertOutbox.id)
                )
            ).scalar_one_or_none()
            await db.commit()
            if row_id is None:
                logger.info(
                    "Alert already waiting to be sent, not queued again: %s", log_ctx
                )
                return
            error = await _deliver(payload, event_id)
            await _record_attempt(db, row_id, 1, error)
            await db.commit()
    except Exception as exc:
        if row_id is not None:
            # stored but the result could not be recorded: the retry loop
            # sends it again with the same event id, which the receiver drops
            logger.warning("Alert outbox update failed for %s: %s", log_ctx, exc)
            return
        logger.warning(
            "Alert outbox unavailable for %s (%s); sending once without retries",
            log_ctx,
            exc,
        )
        error = await _deliver(payload, event_id)
    finally:
        if engine is not None:
            await engine.dispose()
    if error is not None:
        logger.warning("Alert webhook failed for %s: %s (will retry)", log_ctx, error)
    else:
        logger.debug("Alert sent: %s", log_ctx)


async def deliver_due_alerts(limit: int = 50) -> int:
    """Retry undelivered alerts whose wait is over. Returns how many were
    attempted. Rows are locked (SKIP LOCKED) so two backends never send the
    same alert at once. Delivered alerts older than 30 days are removed;
    dead letters are kept."""
    from sqlalchemy import delete, select

    from app.db.models import AlertOutbox
    from app.db.session import get_session_factory

    if not get_settings().alert_webhook_url:
        return 0
    now = datetime.now(timezone.utc)
    async with get_session_factory()() as db:
        rows = (
            (
                await db.execute(
                    select(AlertOutbox)
                    .where(
                        AlertOutbox.status == "pending",
                        AlertOutbox.next_attempt_at <= now,
                    )
                    .order_by(AlertOutbox.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            error = await _deliver(dict(row.payload), row.event_id)
            await _record_attempt(db, row.id, row.attempts + 1, error)
        await db.execute(
            delete(AlertOutbox).where(
                AlertOutbox.status == "sent",
                AlertOutbox.sent_at < now - timedelta(days=_KEEP_SENT_DAYS),
            )
        )
        await db.commit()
    return len(rows)


async def send_task_alert(
    task_id: int,
    event: str,
    detail: str,
    extra: dict[str, object] | None = None,
) -> None:
    """POST a JSON alert payload to ALERT_WEBHOOK_URL.

    No-op when ALERT_WEBHOOK_URL is empty or ALERT_ON_BLOCKED is false
    (for 'blocked' events). Never raises — failures are only logged.
    """
    settings = get_settings()
    if not settings.alert_webhook_url:
        return
    if event == "blocked" and not settings.alert_on_blocked:
        return

    payload: dict[str, object] = {
        "source": "gridiron-dev-dept",
        "event": event,
        "task_id": task_id,
        "detail": detail[:500],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)

    await _post_alert(payload, f"task={task_id} event={event}")


async def send_agent_alert(
    agent_name: str,
    event: str,
    detail: str,
    extra: dict[str, object] | None = None,
) -> None:
    """AUDIT_Q_BATCH16 §89 gap-closure (2026-08-11) — "Notify a supervisor"
    on automatic agent retirement was NO: FleetManager.select() already
    excludes an unhealthy agent (real, code-enforced — see
    agent_registry.py's own health-weight scoring), but nothing ever told a
    human it happened, only an internal metadata field changed. Reuses the
    exact same ALERT_WEBHOOK_URL configuration send_task_alert() already
    uses (one webhook target, not a second notification channel to
    configure) — no-op when unset, matching send_task_alert()'s own
    graceful-degradation contract."""
    settings = get_settings()
    if not settings.alert_webhook_url:
        return

    payload: dict[str, object] = {
        "source": "gridiron-dev-dept",
        "event": f"agent_{event}",
        "agent_name": agent_name,
        "detail": detail[:500],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        payload.update(extra)

    await _post_alert(payload, f"agent={agent_name} event={event}")
