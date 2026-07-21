"""Day 13 — approval_gate.py: generic tracking/indexing over interrupt()-paused
LangGraph threads. Pure DB layer — does not call interrupt() itself (that
already exists and works in app/pipeline/graph.py); this only tracks it.

Every test uses a thread_id prefixed td_ag_ and cleans up its own
pending_approvals rows in a try/finally, matching the established pattern.
"""
from __future__ import annotations

import asyncio

from app.fleet import approval_gate as ag


def _cleanup(thread_id: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import PendingApproval

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread_id))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_record_pending_then_get_pending_round_trip() -> None:
    thread_id = "td_ag_round_trip"
    try:
        rec = ag.record_pending(
            thread_id, "plan_review", {"subtasks_count": 2, "risk_level": "medium"},
            agent_name="decomposer", task_id=4242,
        )
        assert rec.status == "pending"
        assert rec.task_id == 4242
        assert rec.details["subtasks_count"] == 2

        got = ag.get_pending(thread_id)
        assert got is not None
        assert got.id == rec.id
        assert got.action == "plan_review"
    finally:
        _cleanup(thread_id)


def test_get_pending_returns_none_for_unknown_thread() -> None:
    assert ag.get_pending("td_ag_never_existed") is None


def test_list_pending_includes_new_row_and_excludes_decided_ones() -> None:
    thread_id = "td_ag_list_test"
    try:
        ag.record_pending(thread_id, "plan_review", {}, task_id=1)
        pending_ids = {p.thread_id for p in ag.list_pending()}
        assert thread_id in pending_ids

        ag.record_decision(thread_id, approved=True, decided_by="tester")
        pending_ids_after = {p.thread_id for p in ag.list_pending()}
        assert thread_id not in pending_ids_after
    finally:
        _cleanup(thread_id)


def test_record_decision_approved_sets_status_and_decided_by() -> None:
    thread_id = "td_ag_decision_approved"
    try:
        ag.record_pending(thread_id, "plan_review", {}, task_id=2)
        decided = ag.record_decision(thread_id, approved=True, decided_by="alice")
        assert decided is not None
        assert decided.status == "approved"
        assert decided.decided_by == "alice"
        assert decided.decided_at is not None
    finally:
        _cleanup(thread_id)


def test_record_decision_rejected_sets_status_rejected() -> None:
    thread_id = "td_ag_decision_rejected"
    try:
        ag.record_pending(thread_id, "plan_review", {}, task_id=3)
        decided = ag.record_decision(thread_id, approved=False, decided_by="bob")
        assert decided is not None
        assert decided.status == "rejected"
    finally:
        _cleanup(thread_id)


def test_record_decision_on_unknown_thread_returns_none() -> None:
    assert ag.record_decision("td_ag_no_such_thread", approved=True) is None


def test_record_decision_is_idempotent_only_against_pending_rows() -> None:
    """A second decision call against an already-decided thread must not
    silently flip it again — record_decision only matches status='pending'."""
    thread_id = "td_ag_double_decision"
    try:
        ag.record_pending(thread_id, "plan_review", {}, task_id=4)
        first = ag.record_decision(thread_id, approved=True, decided_by="alice")
        assert first is not None and first.status == "approved"

        second = ag.record_decision(thread_id, approved=False, decided_by="bob")
        assert second is None  # no pending row left to decide

        # the original decision must be untouched
        still = ag.get_pending(thread_id)
        assert still is not None
        assert still.status == "approved"
        assert still.decided_by == "alice"
    finally:
        _cleanup(thread_id)
