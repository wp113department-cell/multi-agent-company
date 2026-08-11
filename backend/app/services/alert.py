"""AlertService — fires webhook notifications on notable task events.

Called by API handlers when a task transitions to 'blocked' or 'failed'.
Falls back silently when ALERT_WEBHOOK_URL is not configured.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def _post_alert(payload: dict[str, object], log_ctx: str) -> None:
    """Shared webhook POST — factored out so send_task_alert and
    send_agent_alert don't duplicate the httpx/error-handling boilerplate.
    Never raises — failures are only logged."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(settings.alert_webhook_url, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "Alert webhook returned HTTP %d for %s", resp.status_code, log_ctx
                )
            else:
                logger.debug("Alert sent: %s", log_ctx)
    except Exception as exc:
        logger.warning("Alert webhook error for %s: %s", log_ctx, exc)


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
