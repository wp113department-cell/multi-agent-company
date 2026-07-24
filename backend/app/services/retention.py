"""Log retention service — periodically archives task_logs/agent_runs/
artifacts older than LOG_RETENTION_DAYS.

Runs as a background asyncio task started in main.py lifespan.
Set LOG_RETENTION_DAYS=0 to disable cleanup.

Gap-closure (files/GAPS_ALL_FILES_REPORT.md, 2026-07-23): the Memory System
Specification calls for these rows to be "archived to cheaper storage rather
than deleted" — this previously ran a hard DELETE on task_logs only, with no
retention logic at all for agent_runs/artifacts. All three now flip an
archived/archived_at flag instead (migration 019), matching the pattern
already established in app/fleet/versioned_memory.py's _archive_expired().
A true move to cheaper storage (e.g. S3) is out of scope for this pass — the
archive flag is the honest, minimal fix for "don't permanently destroy data."
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

# table -> (age column to compare against cutoff)
_RETAINED_TABLES: dict[str, str] = {
    "task_logs": "created_at",
    "agent_runs": "started_at",
    "artifacts": "created_at",
}


async def _archive_table(table: str, age_column: str, cutoff: datetime) -> int:
    """Flip archived=true/archived_at=now() for rows older than cutoff.
    Returns the number of rows newly archived (was: number deleted)."""
    factory = get_session_factory()
    # Naive datetime — these columns are all TIMESTAMP WITHOUT TIME ZONE
    # (matches every other timestamp column in this schema); a prior
    # gap-closure found asyncpg raises DataError on a timezone-aware write.
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)

    async with factory() as db:
        result = await db.execute(
            text(
                f"UPDATE {table} SET archived = true, archived_at = :now "
                f"WHERE {age_column} < :cutoff AND archived = false"
            ),
            {"now": now_naive, "cutoff": cutoff},
        )
        await db.commit()
        count: int = getattr(result, "rowcount", 0)
        if count > 0:
            logger.info(
                "Log retention: archived %d %s rows older than %s (cutoff %s)",
                count,
                table,
                age_column,
                cutoff.date(),
            )
        return count


async def _run_cleanup() -> int:
    """Archive rows older than LOG_RETENTION_DAYS across task_logs,
    agent_runs, and artifacts, plus memory_embeddings on its own separate
    MEMORY_EMBEDDINGS_RETENTION_DAYS window (Audit 03 gap-closure,
    2026-07-24 — engineering memory is longer-lived than raw execution logs,
    so it gets its own knob rather than reusing LOG_RETENTION_DAYS, matching
    the precedent versioned_lessons already set with its own
    LESSON_RETENTION_DAYS). Returns the combined count newly archived."""
    settings = get_settings()
    total = 0

    if settings.log_retention_days > 0:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=settings.log_retention_days
        )
        for table, age_column in _RETAINED_TABLES.items():
            total += await _archive_table(table, age_column, cutoff)

    if settings.memory_embeddings_retention_days > 0:
        memory_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=settings.memory_embeddings_retention_days
        )
        total += await _archive_table("memory_embeddings", "created_at", memory_cutoff)

    return total


async def enforce_retention_policy() -> int:
    """Public helper — run one cleanup cycle immediately. Returns the
    combined count of rows newly archived across all retained tables."""
    return await _run_cleanup()


async def start_retention_loop() -> None:
    """Background task: run archival on startup and then every 24 hours."""
    settings = get_settings()
    if settings.log_retention_days <= 0 and settings.memory_embeddings_retention_days <= 0:
        logger.info(
            "Retention disabled (LOG_RETENTION_DAYS=0 and "
            "MEMORY_EMBEDDINGS_RETENTION_DAYS=0)"
        )
        return

    logger.info(
        "Retention started: task_logs/agent_runs/artifacts older than %d days, "
        "memory_embeddings older than %d days, checked every 24 h",
        settings.log_retention_days,
        settings.memory_embeddings_retention_days,
    )

    while True:
        try:
            archived = await _run_cleanup()
            logger.debug("Retention cycle complete, archived=%d", archived)
        except Exception as exc:
            logger.warning("Retention cleanup error: %s", exc)

        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
