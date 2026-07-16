"""Log retention service — periodically deletes task_logs older than LOG_RETENTION_DAYS.

Runs as a background asyncio task started in main.py lifespan.
Set LOG_RETENTION_DAYS=0 to disable cleanup.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.config import get_settings
from app.db.session import get_session_factory

logger = logging.getLogger(__name__)

_CLEANUP_INTERVAL_SECONDS = 24 * 3600  # run once per day


async def _run_cleanup() -> int:
    """Delete task_logs rows older than LOG_RETENTION_DAYS. Returns deleted row count."""
    settings = get_settings()
    if settings.log_retention_days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.log_retention_days)
    factory = get_session_factory()

    async with factory() as db:
        result = await db.execute(
            text("DELETE FROM task_logs WHERE created_at < :cutoff"),
            {"cutoff": cutoff},
        )
        await db.commit()
        count: int = getattr(result, "rowcount", 0)  # rowcount available on CursorResult
        if count > 0:
            logger.info(
                "Log retention: deleted %d task_logs rows older than %d days (cutoff %s)",
                count,
                settings.log_retention_days,
                cutoff.date(),
            )
        return count


async def enforce_retention_policy() -> int:
    """Public helper — run one cleanup cycle immediately. Returns deleted row count."""
    return await _run_cleanup()


async def start_retention_loop() -> None:
    """Background task: run log cleanup on startup and then every 24 hours."""
    settings = get_settings()
    if settings.log_retention_days <= 0:
        logger.info("Log retention disabled (LOG_RETENTION_DAYS=0)")
        return

    logger.info(
        "Log retention started: cleaning logs older than %d days every 24 h",
        settings.log_retention_days,
    )

    while True:
        try:
            deleted = await _run_cleanup()
            logger.debug("Retention cycle complete, deleted=%d", deleted)
        except Exception as exc:
            logger.warning("Retention cleanup error: %s", exc)

        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
