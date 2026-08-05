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
    # Audit 06 correction: archived_at (the column actually written below) is
    # genuinely TIMESTAMP WITHOUT TIME ZONE (migrations 019/022) — that part
    # was correct. But age_column (created_at/started_at) is TIMESTAMP WITH
    # TIME ZONE like most of this schema, contrary to this comment's old,
    # inaccurate claim that "every other timestamp column" is naive. Both
    # binds still work here because this uses raw text() SQL, which doesn't
    # go through SQLAlchemy's ORM type system (the layer where an ORM/DB type
    # mismatch actually causes a crash — see db/models.py's DateTime(timezone=True)
    # fixes and docs/reports/AUDIT_06_INFRASTRUCTURE.md, INFRA-06-001).
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


async def _cleanup_checkpoints(cutoff: datetime) -> int:
    """Blocker (audit_v1.md 4.1 #5): "LangGraph Postgres checkpoint tables
    have no retention/cleanup — unbounded growth." _RETAINED_TABLES above
    never covered checkpoints/checkpoint_blobs/checkpoint_writes, and every
    run_agent_graph() call mints a fresh uuid4 trace_id used as the
    checkpointer thread_id — confirmed no caller ever passes a stable one —
    so every dispatch/retry/subtask/epic permanently creates a brand-new
    LangGraph thread that nothing ever cleaned up.

    Hard DELETE (not archive-flag, unlike the app's own tables above) —
    these three tables are AsyncPostgresSaver's own replay/resume
    scaffolding, not this app's audit history; there is no archived column
    on them (they're framework-owned schema, not an app model) and no
    legitimate reason to keep a checkpoint around after its retention
    window — the run it belonged to is long since finished or abandoned.

    checkpoint_id has no timestamp column to compare against directly, but
    LangGraph's own checkpoint_id is a real UUIDv6 (verified: `SELECT
    checkpoint_id FROM checkpoints LIMIT 5` against this app's own DB
    returns values with the version-6 nibble, e.g.
    '1f184278-3b07-6999-...') — a time-sortable UUID variant that encodes
    its own creation timestamp, decoded here via LangGraph's own bundled
    `langgraph.checkpoint.base.id.UUID.time` (the exact class LangGraph
    itself uses to generate these IDs), not a hand-rolled/guessed format.
    A thread's newest checkpoint_id (MAX() is valid because UUIDv6 is
    lexicographically time-ordered by design — "reordered for improved DB
    locality", the format's own stated purpose) decides whether the whole
    thread is stale; if so, every row for that thread_id is deleted from
    all three tables.
    """
    from langgraph.checkpoint.base.id import UUID as _LGUUID

    _UUID_EPOCH = datetime(1582, 10, 15, tzinfo=timezone.utc)

    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(
            text(
                "SELECT thread_id, MAX(checkpoint_id) AS newest "
                "FROM checkpoints GROUP BY thread_id"
            )
        )
        rows = result.fetchall()

        stale_thread_ids: list[str] = []
        for thread_id, newest_checkpoint_id in rows:
            try:
                parsed = _LGUUID(str(newest_checkpoint_id))
                if parsed.version != 6:
                    continue  # not a decodable time-ordered id — leave alone
                ts = _UUID_EPOCH + timedelta(microseconds=parsed.time / 10)
            except (ValueError, AttributeError):
                continue  # malformed/legacy checkpoint_id — leave alone, not our call to guess
            if ts < cutoff:
                stale_thread_ids.append(str(thread_id))

        if not stale_thread_ids:
            return 0

        total_deleted = 0
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            del_result = await db.execute(
                text(f"DELETE FROM {table} WHERE thread_id = ANY(:thread_ids)"),
                {"thread_ids": stale_thread_ids},
            )
            total_deleted += getattr(del_result, "rowcount", 0) or 0
        await db.commit()

        logger.info(
            "Checkpoint retention: deleted %d row(s) across %d stale thread(s) "
            "(cutoff %s)",
            total_deleted,
            len(stale_thread_ids),
            cutoff.date(),
        )
        return total_deleted


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

    if settings.checkpoint_retention_days > 0:
        checkpoint_cutoff = datetime.now(timezone.utc) - timedelta(
            days=settings.checkpoint_retention_days
        )
        try:
            total += await _cleanup_checkpoints(checkpoint_cutoff)
        except Exception as exc:
            logger.warning("Checkpoint retention cleanup error: %s", exc)

    return total


async def enforce_retention_policy() -> int:
    """Public helper — run one cleanup cycle immediately. Returns the
    combined count of rows newly archived across all retained tables."""
    return await _run_cleanup()


async def start_retention_loop() -> None:
    """Background task: run archival on startup and then every 24 hours."""
    settings = get_settings()
    if (
        settings.log_retention_days <= 0
        and settings.memory_embeddings_retention_days <= 0
        and settings.checkpoint_retention_days <= 0
    ):
        logger.info(
            "Retention disabled (LOG_RETENTION_DAYS=0, "
            "MEMORY_EMBEDDINGS_RETENTION_DAYS=0, and "
            "CHECKPOINT_RETENTION_DAYS=0)"
        )
        return

    logger.info(
        "Retention started: task_logs/agent_runs/artifacts older than %d days, "
        "memory_embeddings older than %d days, LangGraph checkpoints older "
        "than %d days, checked every 24 h",
        settings.log_retention_days,
        settings.memory_embeddings_retention_days,
        settings.checkpoint_retention_days,
    )

    while True:
        try:
            archived = await _run_cleanup()
            logger.debug("Retention cycle complete, archived=%d", archived)
        except Exception as exc:
            logger.warning("Retention cleanup error: %s", exc)

        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
