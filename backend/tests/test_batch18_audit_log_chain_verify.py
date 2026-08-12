"""AUDIT_Q_BATCH18 Bonus-table row 7 gap-closure (2026-08-12) — migration
036 (AUDIT_Q_BATCH11 §96) already built a real DB-enforced hash chain on
audit_log (server-computed entry_hash/prev_hash, append-only triggers), but
nothing ever read entry_hash/prev_hash back to confirm the chain is
actually intact — AuditLog.verify_chain() is that missing read-back.

Every test scopes its check to `since_seq=<seq before this test's own
inserts>` — audit_log is a real, shared, long-lived table with years of
accumulated test-suite history (other tests intentionally break/purge
chain links, e.g. test_batch11_audit_log_tamper_resistance.py), so
asserting global whole-table intactness would be flaky by construction.
`since_seq` is exactly the incremental-check feature this module needs for
that reason in production too, not just in this test file.

Follows test_batch11_audit_log_tamper_resistance.py's own established
pattern (isolated engine per test, global session-factory reset in
teardown, SET LOCAL audit_log.allow_mutation for maintenance-only cleanup).
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


async def _purge(engine: AsyncEngine, entry_id: str) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SET LOCAL audit_log.allow_mutation = 'true'"))
        await conn.execute(
            text("DELETE FROM audit_log WHERE entry_id = :id"), {"id": entry_id}
        )
        await conn.commit()


async def _current_max_seq(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT COALESCE(MAX(seq), 0) FROM audit_log"))
        return int(result.scalar_one())


@pytest.mark.asyncio
async def test_freshly_written_entries_verify_as_intact() -> None:
    engine = _engine()
    log = AuditLog()
    baseline = await _current_max_seq(engine)
    suffix = uuid.uuid4().hex[:8]
    e1 = AuditEntry(
        action_type="chain_verify_test",
        agent_name="test_agent",
        description=f"verify-1-{suffix}",
        details={"nested": {"k": "v"}, "n": 3},
    )
    e2 = AuditEntry(
        action_type="chain_verify_test",
        agent_name="test_agent",
        description=f"verify-2-{suffix}",
        approved_by="alice",
        requires_human_approval=True,
    )
    try:
        await log._write_to_db(e1)
        await log._write_to_db(e2)

        report = await log.verify_chain(since_seq=baseline + 1)

        assert report["intact"] is True
        assert report["breaks"] == []
        assert report["first_break"] is None
        assert report["checked"] == 2
    finally:
        await _purge(engine, e1.entry_id)
        await _purge(engine, e2.entry_id)
        await engine.dispose()
        _reset_global_session_factory()


@pytest.mark.asyncio
async def test_tampered_content_is_detected() -> None:
    """A row whose description was altered after insertion (via the
    maintenance bypass, mirroring what a compromised superuser could do
    even with the append-only triggers in place) must fail content_hash_valid."""
    engine = _engine()
    log = AuditLog()
    baseline = await _current_max_seq(engine)
    entry = AuditEntry(
        action_type="chain_verify_test",
        agent_name="test_agent",
        description=f"pre-tamper-{uuid.uuid4().hex[:8]}",
    )
    try:
        await log._write_to_db(entry)

        async with engine.connect() as conn:
            await conn.execute(text("SET LOCAL audit_log.allow_mutation = 'true'"))
            await conn.execute(
                text(
                    "UPDATE audit_log SET description = 'TAMPERED' WHERE entry_id = :id"
                ),
                {"id": entry.entry_id},
            )
            await conn.commit()

        report = await log.verify_chain(since_seq=baseline + 1)

        assert report["intact"] is False
        tampered_ids = {b["entry_id"] for b in report["breaks"]}
        assert entry.entry_id in tampered_ids
        broken = next(b for b in report["breaks"] if b["entry_id"] == entry.entry_id)
        assert broken["content_hash_valid"] is False
    finally:
        await _purge(engine, entry.entry_id)
        await engine.dispose()
        _reset_global_session_factory()


@pytest.mark.asyncio
async def test_deleted_middle_row_breaks_the_chain_link() -> None:
    """Removing a row from the middle of the chain (bypassing the DELETE
    trigger) must be detected as a broken chain LINK on the following row,
    even though that following row's own content hash is untouched."""
    engine = _engine()
    log = AuditLog()
    baseline = await _current_max_seq(engine)
    suffix = uuid.uuid4().hex[:8]
    e1 = AuditEntry(
        action_type="chain_verify_test",
        agent_name="test_agent",
        description=f"gap-1-{suffix}",
    )
    e2 = AuditEntry(
        action_type="chain_verify_test",
        agent_name="test_agent",
        description=f"gap-2-{suffix}",
    )
    e3 = AuditEntry(
        action_type="chain_verify_test",
        agent_name="test_agent",
        description=f"gap-3-{suffix}",
    )
    try:
        await log._write_to_db(e1)
        await log._write_to_db(e2)
        await log._write_to_db(e3)

        await _purge(engine, e2.entry_id)  # remove the middle row

        report = await log.verify_chain(since_seq=baseline + 1)

        assert report["intact"] is False
        broken = next(
            (b for b in report["breaks"] if b["entry_id"] == e3.entry_id), None
        )
        assert broken is not None
        assert broken["chain_link_valid"] is False
    finally:
        await _purge(engine, e1.entry_id)
        await _purge(engine, e3.entry_id)
        await engine.dispose()
        _reset_global_session_factory()


@pytest.mark.asyncio
async def test_since_seq_anchors_against_the_true_prior_hash() -> None:
    """The first row of a windowed (since_seq > 1) check must be validated
    against the REAL entry_hash of the row before the window, not an
    assumed-empty prev_hash — proves the anchor CTE actually works, not
    just "since_seq=1 happens to work because that's the unwindowed case"."""
    engine = _engine()
    log = AuditLog()
    suffix = uuid.uuid4().hex[:8]
    e1 = AuditEntry(
        action_type="chain_verify_test",
        agent_name="test_agent",
        description=f"anchor-1-{suffix}",
    )
    e2 = AuditEntry(
        action_type="chain_verify_test",
        agent_name="test_agent",
        description=f"anchor-2-{suffix}",
    )
    try:
        await log._write_to_db(e1)
        async with engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("SELECT seq FROM audit_log WHERE entry_id = :id"),
                        {"id": e1.entry_id},
                    )
                )
                .mappings()
                .first()
            )
        e1_seq = row["seq"]
        await log._write_to_db(e2)

        # Window starts exactly at e2 — e1 (the true anchor) is outside it.
        report = await log.verify_chain(since_seq=e1_seq + 1)

        assert report["checked"] == 1
        assert report["intact"] is True
    finally:
        await _purge(engine, e1.entry_id)
        await _purge(engine, e2.entry_id)
        await engine.dispose()
        _reset_global_session_factory()


@pytest.mark.asyncio
async def test_verify_chain_never_raises_on_db_failure(monkeypatch) -> None:
    """A verification call that can't reach the DB must report
    intact=None (never True — "couldn't check" is not "verified clean")
    and never raise past this function, matching every other real-signal-
    not-fabricated convention in this codebase."""
    log = AuditLog()

    def _boom():
        raise RuntimeError("db unreachable")

    monkeypatch.setattr("app.db.session.get_session_factory", _boom)

    report = await log.verify_chain()

    assert report["intact"] is None
    assert report["checked"] == 0
    assert "error" in report
