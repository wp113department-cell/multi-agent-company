"""In-app failure notifications (production audit 08, PROD-08-006).

The owner chose in-app alerts over a Slack/Discord webhook. The webhook path
(services/alert.py) was also only fired from specialized-agent runs, so a task
blocked by the manager, the pipeline or the orphan sweep never alerted anyone.
Here the source of truth is the task itself: every task that is currently
blocked or failed and changed within the window is a notification, with its
newest error log line as the message. No extra table, nothing to keep in
sync, and it survives restarts. "Seen" state is per browser (UI side).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.rbac import require_authenticated

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

_ALERT_STATUSES = ("blocked", "failed")
_ERROR_CATEGORIES = ("error", "pipeline_error", "rejection")


@router.get("")
async def list_notifications(
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _actor: str = Depends(require_authenticated),
) -> dict[str, Any]:
    """Blocked/failed tasks changed in the last `days`, newest first."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await db.execute(
        text(
            "SELECT t.id, t.title, t.status, t.blocked_reason, t.updated_at, "
            "  (SELECT l.message FROM task_logs l WHERE l.task_id = t.id "
            "     AND l.category = ANY(:cats) ORDER BY l.id DESC LIMIT 1) AS last_error "
            "FROM dev_tasks t "
            "WHERE t.status = ANY(:statuses) AND t.updated_at >= :since "
            "ORDER BY t.updated_at DESC LIMIT :limit"
        ),
        {
            "cats": list(_ERROR_CATEGORIES),
            "statuses": list(_ALERT_STATUSES),
            "since": since,
            "limit": limit,
        },
    )
    items = []
    for r in rows.fetchall():
        reason = r.last_error or (
            f"Blocked ({r.blocked_reason})" if r.blocked_reason else None
        )
        items.append(
            {
                "taskId": r.id,
                "title": r.title,
                "status": r.status,
                "blockedReason": r.blocked_reason,
                "message": (reason or f"Task {r.status}")[:300],
                "at": r.updated_at.isoformat(),
            }
        )
    return {"items": items, "serverTime": datetime.now(timezone.utc).isoformat()}
