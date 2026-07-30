"""Gap-closure Day 7 (answers.md Q96, migration 025) — real-DB proof that the
`audit_log` table now exists with the shape app/fleet/audit_log.py's
_write_to_db() has always assumed, and that a real AuditLog.append() call
durably round-trips through it (not just the in-process ring buffer).

Before migration 025, every _write_to_db() INSERT failed against a
nonexistent table and was silently swallowed by its own `except Exception:
pass` (by design — a broken audit sink must never block or fail the
caller) — meaning audit history never survived a process restart. This test
proves that gap is closed for real, not just that the ring buffer still
works (which was never in question).

Gap-closure Day 10 (Gap Audit Protocol, first checkpoint): AuditLog.
_write_to_db() uses the process-wide app.db.session.get_session_factory()
singleton internally (it has no caller-supplied session parameter) — the
same shared-engine hazard test_retention_archive.py already documented and
fixed for enforce_retention_policy(). Reproduced live: running this file's
_write_to_db()-calling tests before test_repo_scoping_race_fix.py (whose
_dispatch_decision also touches get_session_factory()) left that later
test's global engine bound to this file's already-closed pytest-asyncio
event loop, failing with "RuntimeError: Event loop is closed" — bisected
down to a minimal 2-file repro before fixing. Both tests that call
_write_to_db() now reset the global engine/session-factory singleton in
their own teardown, so a later test in the same process always gets one
freshly bound to its own event loop.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from app.fleet.audit_log import AuditEntry, AuditLog


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _reset_global_session_factory() -> None:
    """See module docstring — AuditLog._write_to_db() binds
    app.db.session's process-wide engine/session-factory singleton to
    *this* test's event loop; reset it so a later test's own event loop
    doesn't inherit an already-closed one."""
    import app.db.session as _sess

    _sess._engine = None
    _sess._session_factory = None


@pytest.mark.asyncio
async def test_audit_log_table_exists_with_expected_columns() -> None:
    engine = _engine()
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'audit_log'"
                )
            )
            columns = {row[0] for row in result.fetchall()}
        assert columns == {
            "entry_id",
            "trace_id",
            "timestamp",
            "action_type",
            "agent_name",
            "task_id",
            "description",
            "details",
            "outcome",
            "requires_human_approval",
            "approved_by",
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_write_to_db_round_trips_a_real_entry() -> None:
    """Calls AuditLog._write_to_db() directly (bypassing the fire-and-forget
    asyncio.create_task() wrapper, which is a scheduling detail unrelated to
    whether the INSERT itself is correct) and confirms the row is really
    there afterward, with details (JSONB) intact."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    log = AuditLog()
    entry = AuditEntry(
        action_type="test_action",
        agent_name="test_agent",
        task_id=f"task-{suffix}",
        description="a round-trip test entry",
        details={"key": "value", "n": 3},
        outcome="success",
        requires_human_approval=True,
        approved_by="tester",
        trace_id=f"trace-{suffix}",
    )
    try:
        await log._write_to_db(entry)

        async with engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("SELECT * FROM audit_log WHERE entry_id = :id"),
                        {"id": entry.entry_id},
                    )
                )
                .mappings()
                .first()
            )

        assert row is not None, "entry must have durably persisted to audit_log"
        assert row["action_type"] == "test_action"
        assert row["agent_name"] == "test_agent"
        assert row["task_id"] == f"task-{suffix}"
        assert row["details"] == {"key": "value", "n": 3}
        assert row["outcome"] == "success"
        assert row["requires_human_approval"] is True
        assert row["approved_by"] == "tester"
        assert row["trace_id"] == f"trace-{suffix}"
    finally:
        async with engine.connect() as conn:
            await conn.execute(
                text("DELETE FROM audit_log WHERE entry_id = :id"),
                {"id": entry.entry_id},
            )
            await conn.commit()
        await engine.dispose()
        _reset_global_session_factory()


@pytest.mark.asyncio
async def test_write_to_db_upsert_is_idempotent_on_conflict() -> None:
    """The INSERT uses ON CONFLICT (entry_id) DO NOTHING — writing the same
    entry_id twice must not raise and must not duplicate the row."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    log = AuditLog()
    entry = AuditEntry(
        action_type="test_action",
        agent_name="test_agent",
        description="idempotency check",
        trace_id=f"trace-{suffix}",
    )
    try:
        await log._write_to_db(entry)
        await log._write_to_db(entry)  # same entry_id — must not raise

        async with engine.connect() as conn:
            count = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM audit_log WHERE entry_id = :id"),
                    {"id": entry.entry_id},
                )
            ).scalar_one()
        assert count == 1
    finally:
        async with engine.connect() as conn:
            await conn.execute(
                text("DELETE FROM audit_log WHERE entry_id = :id"),
                {"id": entry.entry_id},
            )
            await conn.commit()
        await engine.dispose()
        _reset_global_session_factory()
