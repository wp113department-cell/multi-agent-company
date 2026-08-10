"""Real held file locks for epic coding — app/db/models.py::EpicFileLock.

Batch 2 audit gap-closure (§2 "Duplicate work prevented"):
`conflict_guard.check_file_conflicts()` is a real, useful check — but it is
only a point-in-time READ of other epics' `architect_plan.impacted_files`,
not a HELD lock. A second epic whose own check happened to run in the gap
between that read and this epic's own `_conflict_check_node` completing
could still race in and start coding the same files. This module is the
real held lock: a `UNIQUE` constraint on `file_path` (migration 039) means
Postgres itself — not application-level timing — guarantees at most one
epic can ever hold a row for a given file at once.

Called from `app/agents/manager.py`: `reserve_epic_files()` right after
`check_file_conflicts()` passes in `_conflict_check_node` (right before the
epic enters coding), `release_epic_files()` in `_finalize_node` alongside
the existing `clear_epic_scratchpad()` call, on both the halted and
ready-for-review terminal paths.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import EpicFileLock

logger = logging.getLogger(__name__)


async def reserve_epic_files(
    candidate_files: list[str],
    epic_id: str,
    db: AsyncSession,
) -> str | None:
    """Atomically acquire a held lock on every file in `candidate_files`
    for `epic_id`. Returns None on success (every lock acquired). Returns
    a conflict description — and leaves NO partial locks held — if any
    file is already locked by ANOTHER epic: an all-or-nothing acquire via
    a SAVEPOINT (`AsyncSession.begin_nested()`), so a losing epic never
    ends up holding a subset of files it happened to "win" the race on.

    Expired locks (`settings.epic_file_lock_ttl_seconds`) are reaped
    before the acquire attempt — a stale lock from a crashed epic (one
    that never reached `_finalize_node`'s release call) must not
    permanently deadlock a file for every future epic.
    """
    if not candidate_files:
        return None

    candidate_set = sorted(set(candidate_files))
    now = datetime.now(timezone.utc)

    await db.execute(delete(EpicFileLock).where(EpicFileLock.expires_at < now))

    try:
        async with db.begin_nested():
            for path in candidate_set:
                db.add(
                    EpicFileLock(
                        epic_id=epic_id,
                        file_path=path,
                        expires_at=now
                        + timedelta(
                            seconds=get_settings().epic_file_lock_ttl_seconds
                        ),
                    )
                )
            await db.flush()
    except IntegrityError:
        # Lost the race — the SAVEPOINT rollback (automatic on exception
        # exit from `begin_nested()`) already undid every lock THIS call
        # attempted, so no partial state is left behind. Best-effort: find
        # out which file(s) and which epic(s) for a useful message.
        result = await db.execute(
            select(EpicFileLock.epic_id, EpicFileLock.file_path).where(
                EpicFileLock.file_path.in_(candidate_set),
                EpicFileLock.epic_id != epic_id,
            )
        )
        holders = result.all()
        if holders:
            by_epic: dict[str, list[str]] = {}
            for holder_epic_id, file_path in holders:
                by_epic.setdefault(holder_epic_id, []).append(file_path)
            detail = "; ".join(
                f"epic {e} holds {sorted(files)}" for e, files in by_epic.items()
            )
            return f"File lock conflict: {detail}"
        return (
            "File lock conflict: another epic acquired a lock on one of "
            "these files in the window between the check and the reserve"
        )

    return None


async def release_epic_files(epic_id: str, db: AsyncSession) -> None:
    """Release every file lock held by `epic_id` — called once the epic
    reaches a terminal state (halted or ready_for_review), mirroring
    `app/fleet/scratchpad.py`'s own `clear_epic_scratchpad()` at the same
    call sites. Never raises — a failed release must not fail epic
    finalization; `settings.epic_file_lock_ttl_seconds` is the backstop if
    this ever silently fails.
    """
    try:
        await db.execute(delete(EpicFileLock).where(EpicFileLock.epic_id == epic_id))
    except Exception:
        logger.warning(
            "Could not release file locks for epic %s (non-fatal; TTL will "
            "expire them)",
            epic_id,
            exc_info=True,
        )
