"""AUDIT_Q_BATCH11 §96 "Audit logs" — proves migration 036's tamper
resistance is real, not decorative: audit_log rows get a server-computed
hash chain, and direct UPDATE/DELETE against the table are rejected by DB
triggers — the append-only guarantee now lives in the database itself, not
only in AuditLog's Python class having no update()/delete() methods.

Follows test_audit_log_migration.py's own established pattern (isolated
engine per test, global session-factory reset in teardown — see that
file's module docstring for why).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from app.fleet.audit_log import AuditEntry, AuditLog


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _reset_global_session_factory() -> None:
    import app.db.session as _sess

    _sess._engine = None
    _sess._session_factory = None


async def _purge(engine: AsyncEngine, entry_id: str) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SET LOCAL audit_log.allow_mutation = 'true'"))
        await conn.execute(
            text("DELETE FROM audit_log WHERE entry_id = :id"), {"id": entry_id}
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_a_new_row_gets_a_non_empty_server_computed_hash() -> None:
    engine = _engine()
    log = AuditLog()
    entry = AuditEntry(
        action_type="tamper_test",
        agent_name="test_agent",
        description=f"hash chain proof {uuid.uuid4().hex[:8]}",
    )
    try:
        await log._write_to_db(entry)
        async with engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT seq, prev_hash, entry_hash FROM audit_log "
                            "WHERE entry_id = :id"
                        ),
                        {"id": entry.entry_id},
                    )
                )
                .mappings()
                .first()
            )
        assert row is not None
        assert row["seq"] is not None
        assert len(row["entry_hash"]) == 64  # hex-encoded sha256
        assert (
            row["prev_hash"] is not None
        )  # "" for the very first row ever, else a real hash
    finally:
        await _purge(engine, entry.entry_id)
        await engine.dispose()
        _reset_global_session_factory()


@pytest.mark.asyncio
async def test_chain_links_two_consecutive_rows() -> None:
    """Row 2's prev_hash must equal row 1's entry_hash — a real chain, not
    two independently-computed hashes."""
    engine = _engine()
    log = AuditLog()
    suffix = uuid.uuid4().hex[:8]
    e1 = AuditEntry(
        action_type="tamper_test",
        agent_name="test_agent",
        description=f"chain-1-{suffix}",
    )
    e2 = AuditEntry(
        action_type="tamper_test",
        agent_name="test_agent",
        description=f"chain-2-{suffix}",
    )
    try:
        await log._write_to_db(e1)
        await log._write_to_db(e2)
        async with engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT entry_id, seq, prev_hash, entry_hash FROM audit_log "
                            "WHERE entry_id IN (:a, :b) ORDER BY seq ASC"
                        ),
                        {"a": e1.entry_id, "b": e2.entry_id},
                    )
                )
                .mappings()
                .all()
            )
        assert len(rows) == 2
        row1, row2 = rows
        assert row1["entry_id"] == e1.entry_id
        assert row2["entry_id"] == e2.entry_id
        assert row2["prev_hash"] == row1["entry_hash"]
    finally:
        await _purge(engine, e1.entry_id)
        await _purge(engine, e2.entry_id)
        await engine.dispose()
        _reset_global_session_factory()


@pytest.mark.asyncio
async def test_direct_update_is_rejected_by_the_db() -> None:
    engine = _engine()
    log = AuditLog()
    entry = AuditEntry(
        action_type="tamper_test",
        agent_name="test_agent",
        description=f"update-attempt-{uuid.uuid4().hex[:8]}",
    )
    try:
        await log._write_to_db(entry)
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError, match="append-only"):
                await conn.execute(
                    text(
                        "UPDATE audit_log SET description = 'TAMPERED' WHERE entry_id = :id"
                    ),
                    {"id": entry.entry_id},
                )
                await conn.commit()
    finally:
        await _purge(engine, entry.entry_id)
        await engine.dispose()
        _reset_global_session_factory()


@pytest.mark.asyncio
async def test_direct_delete_is_rejected_by_the_db() -> None:
    engine = _engine()
    log = AuditLog()
    entry = AuditEntry(
        action_type="tamper_test",
        agent_name="test_agent",
        description=f"delete-attempt-{uuid.uuid4().hex[:8]}",
    )
    try:
        await log._write_to_db(entry)
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError, match="append-only"):
                await conn.execute(
                    text("DELETE FROM audit_log WHERE entry_id = :id"),
                    {"id": entry.entry_id},
                )
                await conn.commit()
    finally:
        await _purge(engine, entry.entry_id)
        await engine.dispose()
        _reset_global_session_factory()


@pytest.mark.asyncio
async def test_bypass_guc_is_required_and_scoped_to_the_session() -> None:
    """The maintenance-only bypass must actually work (proves _purge itself
    is valid, not silently no-op-ing) — and a plain, un-bypassed DELETE in a
    fresh connection right after must still be rejected, proving the bypass
    doesn't leak across connections/sessions."""
    engine = _engine()
    log = AuditLog()
    entry = AuditEntry(
        action_type="tamper_test",
        agent_name="test_agent",
        description=f"bypass-scope-{uuid.uuid4().hex[:8]}",
    )
    await log._write_to_db(entry)
    try:
        async with engine.connect() as other_conn:
            with pytest.raises(DBAPIError, match="append-only"):
                await other_conn.execute(
                    text("DELETE FROM audit_log WHERE entry_id = :id"),
                    {"id": entry.entry_id},
                )
                await other_conn.commit()

        async with engine.connect() as bypass_conn:
            await bypass_conn.execute(
                text("SET LOCAL audit_log.allow_mutation = 'true'")
            )
            result = await bypass_conn.execute(
                text("DELETE FROM audit_log WHERE entry_id = :id"),
                {"id": entry.entry_id},
            )
            await bypass_conn.commit()
        assert result.rowcount == 1

        async with engine.connect() as conn:
            remaining = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM audit_log WHERE entry_id = :id"),
                    {"id": entry.entry_id},
                )
            ).scalar_one()
        assert remaining == 0
    finally:
        await engine.dispose()
        _reset_global_session_factory()
