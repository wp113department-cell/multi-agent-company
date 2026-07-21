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

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(settings.alert_webhook_url, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "Alert webhook returned HTTP %d for task %d event=%s",
                    resp.status_code,
                    task_id,
                    event,
                )
            else:
                logger.debug("Alert sent: task=%d event=%s", task_id, event)
    except Exception as exc:
        logger.warning("Alert webhook error for task %d: %s", task_id, exc)
