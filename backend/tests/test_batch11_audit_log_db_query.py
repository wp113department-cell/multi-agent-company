"""AUDIT_Q_BATCH11 §96 "Audit logs" — proves AuditLog's new *_async query
methods (recent_async/by_trace_async/by_task_async/approvals_async) read
from the durable `audit_log` DB table, not just the in-process ring buffer.

Before this fix, recent()/by_trace()/by_task() only ever read the ring
buffer: capped at 2000 entries and reset to empty on every process
restart, even though _write_to_db() had already been durably persisting
every entry the whole time (test_audit_log_migration.py proves the write
side works). This proves the read side now actually reaches that same
table — each test writes with `log._write_to_db()` directly (bypassing the
ring buffer's append()) against one AuditLog instance, then queries with a
SEPARATE, freshly constructed AuditLog instance whose ring buffer is
empty — so a pass here can only mean the DB query path is real, not that
the ring buffer happened to still hold the entry.

Follows test_audit_log_migration.py's own established pattern exactly,
including the shared-engine/event-loop reset in teardown (AuditLog's own
DB helpers bind app.db.session's process-wide engine singleton to whichever
event loop calls them first; a later test in the same process needs a
fresh one bound to ITS OWN loop, or it fails with "Event loop is closed" —
bisected and documented in that file already).
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
    import app.db.session as _sess

    _sess._engine = None
    _sess._session_factory = None


async def _cleanup(engine: AsyncEngine, entry_ids: list[str]) -> None:
    # migration 036 made audit_log genuinely append-only at the DB layer
    # (BEFORE DELETE/UPDATE triggers) — cleanup must opt into the same
    # maintenance-only bypass GUC real retention-purge tooling would use.
    async with engine.connect() as conn:
        await conn.execute(text("SET LOCAL audit_log.allow_mutation = 'true'"))
        await conn.execute(
            text("DELETE FROM audit_log WHERE entry_id = ANY(:ids)"),
            {"ids": entry_ids},
        )
        await conn.commit()
    await engine.dispose()
    _reset_global_session_factory()


@pytest.mark.asyncio
async def test_recent_async_survives_an_empty_ring_buffer() -> None:
    """The defining proof: write via one AuditLog, read via a brand-new one
    whose ring buffer never saw the entry — recent_async() must still find
    it in the DB, which recent() (ring-buffer-only) provably cannot do."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    writer = AuditLog()
    entry = AuditEntry(
        action_type="test_recent_async",
        agent_name="test_agent",
        description=f"recent_async proof {suffix}",
        trace_id=f"trace-{suffix}",
    )
    try:
        await writer._write_to_db(entry)

        fresh_reader = AuditLog()  # empty ring buffer — never saw `entry`
        assert fresh_reader.recent(50) == []  # ring-buffer-only: can't see it

        found = await fresh_reader.recent_async(50)
        assert any(e.entry_id == entry.entry_id for e in found)
        matched = next(e for e in found if e.entry_id == entry.entry_id)
        assert matched.action_type == "test_recent_async"
        assert matched.description == f"recent_async proof {suffix}"
    finally:
        await _cleanup(engine, [entry.entry_id])


@pytest.mark.asyncio
async def test_by_trace_async_reads_the_db() -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    trace_id = f"trace-{suffix}"
    writer = AuditLog()
    e1 = AuditEntry(
        action_type="op1", agent_name="agent", description="a1", trace_id=trace_id
    )
    e2 = AuditEntry(
        action_type="op2", agent_name="agent", description="a2", trace_id=trace_id
    )
    other = AuditEntry(
        action_type="op3",
        agent_name="agent",
        description="unrelated",
        trace_id=f"other-{suffix}",
    )
    try:
        await writer._write_to_db(e1)
        await writer._write_to_db(e2)
        await writer._write_to_db(other)

        fresh_reader = AuditLog()
        found = await fresh_reader.by_trace_async(trace_id)
        found_ids = {e.entry_id for e in found}
        assert e1.entry_id in found_ids
        assert e2.entry_id in found_ids
        assert other.entry_id not in found_ids
    finally:
        await _cleanup(engine, [e1.entry_id, e2.entry_id, other.entry_id])


@pytest.mark.asyncio
async def test_by_task_async_reads_the_db() -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"task-{suffix}"
    writer = AuditLog()
    entry = AuditEntry(
        action_type="op", agent_name="agent", description="a1", task_id=task_id
    )
    try:
        await writer._write_to_db(entry)

        fresh_reader = AuditLog()
        found = await fresh_reader.by_task_async(task_id)
        assert len(found) == 1
        assert found[0].entry_id == entry.entry_id
        assert found[0].task_id == task_id
    finally:
        await _cleanup(engine, [entry.entry_id])


@pytest.mark.asyncio
async def test_approvals_async_filters_to_human_approval_entries() -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    writer = AuditLog()
    approval = AuditEntry(
        action_type="git_push",
        agent_name="agent",
        description=f"approval {suffix}",
        requires_human_approval=True,
        outcome="approved",
        approved_by="tester",
        trace_id=f"trace-appr-{suffix}",
    )
    non_approval = AuditEntry(
        action_type="file_write",
        agent_name="agent",
        description=f"non-approval {suffix}",
        requires_human_approval=False,
        trace_id=f"trace-non-{suffix}",
    )
    try:
        await writer._write_to_db(approval)
        await writer._write_to_db(non_approval)

        fresh_reader = AuditLog()
        found = await fresh_reader.approvals_async(limit=200)
        found_ids = {e.entry_id for e in found}
        assert approval.entry_id in found_ids
        assert non_approval.entry_id not in found_ids
    finally:
        await _cleanup(engine, [approval.entry_id, non_approval.entry_id])


@pytest.mark.asyncio
async def test_async_queries_fall_back_to_ring_buffer_on_db_failure() -> None:
    """A broken DB query path must degrade to the ring buffer, not raise —
    matching append()'s own established "audit must never block/fail the
    caller" philosophy."""
    log = AuditLog()
    log.append("op", "agent", "ring-buffer-only entry", trace_id="trace-fallback")

    async def _boom(**kwargs: object) -> list[AuditEntry]:
        raise RuntimeError("simulated DB outage")

    log._query_db = _boom  # type: ignore[method-assign]

    result = await log.recent_async(10)
    assert any(e.description == "ring-buffer-only entry" for e in result)
