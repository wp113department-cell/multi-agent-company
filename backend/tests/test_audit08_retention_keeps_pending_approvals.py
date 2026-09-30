"""Production audit 08 (2026-09-30): checkpoint retention must not delete a
thread whose plan is still waiting for human approval.

Before: any thread whose newest checkpoint was older than
CHECKPOINT_RETENTION_DAYS (30) was deleted, pending approval or not — so a plan
left unapproved for a month lost its checkpoint and "Approve" then failed.
Real Postgres, real retention code.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import new_isolated_async_engine
from app.services.retention import _cleanup_checkpoints

_UUID_EPOCH = datetime(1582, 10, 15, tzinfo=timezone.utc)


def _uuid6_at(ts: datetime) -> str:
    """A time-ordered UUIDv6 for a given moment (what LangGraph writes)."""
    t = int((ts - _UUID_EPOCH).total_seconds() * 10_000_000)
    time_high = (t >> 28) & 0xFFFFFFFF
    time_mid = (t >> 12) & 0xFFFF
    time_low_ver = (t & 0x0FFF) | 0x6000
    clock_seq = (secrets.randbits(14)) | 0x8000
    node = secrets.randbits(48)
    return (
        f"{time_high:08x}-{time_mid:04x}-{time_low_ver:04x}-{clock_seq:04x}-{node:012x}"
    )


async def _setup_and_run() -> tuple[bool, bool]:
    engine = new_isolated_async_engine()
    old = datetime.now(timezone.utc) - timedelta(days=90)
    waiting = f"audit08-waiting-{uuid.uuid4().hex[:8]}"
    abandoned = f"audit08-abandoned-{uuid.uuid4().hex[:8]}"
    try:
        async with async_sessionmaker(engine)() as db:
            for thread in (waiting, abandoned):
                await db.execute(
                    text(
                        "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, "
                        "checkpoint, metadata) VALUES (:t, '', :c, CAST(:j AS jsonb), '{}')"
                    ),
                    {"t": thread, "c": _uuid6_at(old), "j": json.dumps({"v": 1})},
                )
            await db.execute(
                text(
                    "INSERT INTO pending_approvals (thread_id, action, details, status, "
                    "agent_name, created_at) VALUES (:t, 'plan_review', '{}', 'pending', "
                    "'manager', now())"
                ),
                {"t": waiting},
            )
            await db.commit()

        await _cleanup_checkpoints(datetime.now(timezone.utc) - timedelta(days=30))

        async with async_sessionmaker(engine)() as db:
            rows = await db.execute(
                text("SELECT thread_id FROM checkpoints WHERE thread_id = ANY(:ids)"),
                {"ids": [waiting, abandoned]},
            )
            left = {r[0] for r in rows.fetchall()}
            await db.execute(
                text("DELETE FROM checkpoints WHERE thread_id = ANY(:ids)"),
                {"ids": [waiting, abandoned]},
            )
            await db.execute(
                text("DELETE FROM pending_approvals WHERE thread_id = :t"),
                {"t": waiting},
            )
            await db.commit()
        return waiting in left, abandoned in left
    finally:
        await engine.dispose()


def test_pending_approval_thread_is_kept_abandoned_one_is_deleted() -> None:
    waiting_kept, abandoned_kept = asyncio.run(_setup_and_run())
    assert waiting_kept, "a plan still awaiting approval lost its checkpoint"
    assert not abandoned_kept, "retention no longer deletes genuinely stale threads"
