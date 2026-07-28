"""Shared scratchpad — MASTER_AGENT_v2.md Phase 1.7.

Ephemeral, epic-scoped key-value store for cross-agent discoveries,
hypotheses, TODOs, and partial findings during a single epic's execution —
distinct from every permanent memory_embeddings category (task/failure/
architecture/learning/procedure, app/memory/store.py). Agents dispatched
within the same epic (backend_dev, frontend_dev, qa, reviewer, coordinated by
app/agents/manager.py) can read/write short-lived state here before anything
is worth promoting to permanent memory.

Backed by Postgres, not Redis — this project's queue_backend defaults to
"asyncio" and redis_streams_enabled defaults to False (app/config.py), so
Redis is optional, opt-in infrastructure here; Postgres is not. A
Redis-backed scratchpad would silently no-op in the default configuration.

Rows are deleted outright — never archived — on epic completion
(clear_epic_scratchpad, called from app/agents/manager.py at both epic-halt
and epic-ready-for-review) or TTL expiry (settings.scratchpad_ttl_seconds),
whichever comes first. This must never become a fifth permanent memory
system: a finding worth keeping should be explicitly promoted via the
record_learning tool (app/agents/tools.py, Phase 1.4) into memory_embeddings,
not left to accumulate here indefinitely.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import EpicScratchpad

logger = logging.getLogger(__name__)


async def write_entry(
    epic_id: str,
    key: str,
    value: Any,
    agent_name: str,
    db: AsyncSession,
    ttl_seconds: int | None = None,
) -> bool:
    """Write (or overwrite) one scratchpad entry for an epic. Key-value:
    a second write with the same (epic_id, key) replaces the first — this is
    a live working-set, not an append-only log. Returns True on success,
    False on any failure (never raises — a broken scratchpad write must not
    break the calling agent's turn).
    """
    ttl = (
        ttl_seconds
        if ttl_seconds is not None
        else get_settings().scratchpad_ttl_seconds
    )
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)

    try:
        existing = (
            await db.execute(
                select(EpicScratchpad).where(
                    EpicScratchpad.epic_id == epic_id, EpicScratchpad.key == key
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            existing.value = value
            existing.agent_name = agent_name
            existing.expires_at = expires_at
        else:
            db.add(
                EpicScratchpad(
                    epic_id=epic_id,
                    key=key,
                    value=value,
                    agent_name=agent_name,
                    expires_at=expires_at,
                )
            )
        await db.commit()
        return True
    except Exception as exc:
        logger.warning(
            "scratchpad: write failed for epic=%s key=%s: %s", epic_id, key, exc
        )
        await db.rollback()
        return False


async def read_entries(
    epic_id: str,
    db: AsyncSession,
    key: str | None = None,
) -> list[dict[str, Any]]:
    """Read non-expired scratchpad entries for an epic, optionally filtered
    to one key. Returns [] on any failure or when nothing matches — never
    raises. Each entry: {"key", "value", "agent_name", "created_at"}.
    """
    try:
        now = datetime.now(timezone.utc)
        stmt = select(EpicScratchpad).where(
            EpicScratchpad.epic_id == epic_id, EpicScratchpad.expires_at > now
        )
        if key is not None:
            stmt = stmt.where(EpicScratchpad.key == key)
        rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "key": row.key,
                "value": row.value,
                "agent_name": row.agent_name,
                "created_at": row.created_at.isoformat() if row.created_at else "",
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning("scratchpad: read failed for epic=%s: %s", epic_id, exc)
        return []


async def clear_epic_scratchpad(epic_id: str, db: AsyncSession) -> int:
    """Delete every scratchpad entry for an epic — called when the epic
    reaches a terminal state (halted or ready_for_review). Returns the
    number of rows deleted, or 0 on failure (never raises)."""
    try:
        result = await db.execute(
            delete(EpicScratchpad).where(EpicScratchpad.epic_id == epic_id)
        )
        await db.commit()
        deleted: int = getattr(result, "rowcount", 0) or 0
        if deleted:
            logger.info("scratchpad: cleared %d entries for epic %s", deleted, epic_id)
        return deleted
    except Exception as exc:
        logger.warning("scratchpad: clear failed for epic=%s: %s", epic_id, exc)
        await db.rollback()
        return 0


async def expire_stale_entries(db: AsyncSession) -> int:
    """Delete every scratchpad entry past its TTL, regardless of epic state
    — the backstop for an epic that stalls or is abandoned without ever
    reaching a terminal state. Intended for a periodic sweep (matching
    app/services/retention.py's existing pattern), not a per-request call."""
    try:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            delete(EpicScratchpad).where(EpicScratchpad.expires_at <= now)
        )
        await db.commit()
        deleted: int = getattr(result, "rowcount", 0) or 0
        if deleted:
            logger.info("scratchpad: expired %d stale entries", deleted)
        return deleted
    except Exception as exc:
        logger.warning("scratchpad: expiry sweep failed: %s", exc)
        await db.rollback()
        return 0


# ---------------------------------------------------------------------------
# Sync bridges — for callers that cannot await (e.g. a LangGraph tool
# handler; base_graph.py's graph.invoke() is sync, matching the same
# constraint Phase 1.3/1.4/1.5's sync bridges were built for).
# ---------------------------------------------------------------------------


def write_entry_sync(
    epic_id: str,
    key: str,
    value: Any,
    agent_name: str,
    ttl_seconds: int | None = None,
) -> bool:
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> bool:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await write_entry(
                    epic_id, key, value, agent_name, session, ttl_seconds=ttl_seconds
                )
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning("write_entry_sync failed: %s", exc)
        return False


def read_entries_sync(epic_id: str, key: str | None = None) -> list[dict[str, Any]]:
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import new_isolated_async_engine

    async def _run() -> list[dict[str, Any]]:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await read_entries(epic_id, session, key=key)
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.warning("read_entries_sync failed: %s", exc)
        return []
