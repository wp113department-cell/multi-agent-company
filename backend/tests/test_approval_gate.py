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
                await session.execute(
                    delete(PendingApproval).where(
                        PendingApproval.thread_id == thread_id
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_record_pending_then_get_pending_round_trip() -> None:
    thread_id = "td_ag_round_trip"
    try:
        rec = ag.record_pending(
            thread_id,
            "plan_review",
            {"subtasks_count": 2, "risk_level": "medium"},
            agent_name="decomposer",
            task_id=4242,
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


def test_request_human_input_writes_kind_as_action_and_blocking_in_details() -> None:
    """MASTER_AGENT_v2.md Phase 5.5 — request_human_input() is the single
    generalized entry point; kind becomes the row's real `action` (the
    column app/api/approvals.py's dispatch already switches on by exact
    value), and blocking is folded into details for API/dashboard
    consumers, without request_human_input() owning any pause mechanics
    itself."""
    thread_id = "td_ag_request_human_input"
    try:
        rec = ag.request_human_input(
            "plan_review",
            {"risk_level": "high"},
            agent_name="decomposer",
            thread_id=thread_id,
            task_id=99,
            blocking=True,
            description="Plan review for task 99",
        )
        assert rec.action == "plan_review"
        assert rec.details["risk_level"] == "high"
        assert rec.details["blocking"] is True

        got = ag.get_pending(thread_id)
        assert got is not None
        assert got.id == rec.id
    finally:
        _cleanup(thread_id)


def test_request_human_input_non_blocking_kind_records_blocking_false() -> None:
    thread_id = "td_ag_request_human_input_nonblocking"
    try:
        rec = ag.request_human_input(
            "clarification",
            {"question": "Which provider?"},
            agent_name="planner",
            thread_id=thread_id,
            task_id=None,
            blocking=False,
        )
        assert rec.action == "clarification"
        assert rec.details["blocking"] is False
    finally:
        _cleanup(thread_id)


def test_request_human_input_logs_the_request_to_the_audit_log() -> None:
    """Previously only DECISIONS were audit-logged (see
    resume_planning_pipeline's get_audit_log().record_approval() call) — the
    request itself never appeared in the audit trail until it was later
    decided. request_human_input() closes that gap."""
    from app.fleet.audit_log import get_audit_log

    thread_id = "td_ag_request_human_input_audit"
    try:
        ag.request_human_input(
            "plan_review",
            {"risk_level": "low"},
            agent_name="decomposer",
            thread_id=thread_id,
            task_id=123,
            blocking=True,
            description="Plan review for task 123",
        )
        matches = get_audit_log().by_trace(thread_id)
        assert matches, "expected a request-time audit entry for this thread_id"
        entry = matches[-1]
        assert entry.action_type == "plan_review"
        assert entry.outcome == "pending"
        assert entry.requires_human_approval is True
        assert entry.task_id == "123"
    finally:
        _cleanup(thread_id)


def test_arequest_human_input_async_facade_round_trips() -> None:
    thread_id = "td_ag_arequest_human_input"
    try:

        async def _run() -> ag.PendingApprovalRecord:
            return await ag.arequest_human_input(
                "git_push",
                {"branch": "agent/task-7"},
                agent_name="manager",
                thread_id=thread_id,
                task_id=7,
                blocking=True,
            )

        rec = asyncio.run(_run())
        assert rec.action == "git_push"
        assert rec.details["blocking"] is True

        got = ag.get_pending(thread_id)
        assert got is not None
        assert got.id == rec.id
    finally:
        _cleanup(thread_id)


def test_record_pending_supersedes_prior_undecided_row_for_same_thread() -> None:
    """Gap-closure (2026-07-21): restarting a task via POST /tasks/{id}/restart
    while paused at human_review previously left the old row orphaned as
    "pending" forever — a stale duplicate list_pending() could never clear."""
    thread_id = "td_ag_restart_supersede"
    try:
        first = ag.record_pending(thread_id, "plan_review", {"round": 1}, task_id=5)
        assert first.status == "pending"

        second = ag.record_pending(thread_id, "plan_review", {"round": 2}, task_id=5)
        assert second.status == "pending"
        assert second.id != first.id

        # the old row must no longer show up as pending
        pending_ids = {p.id for p in ag.list_pending() if p.thread_id == thread_id}
        assert pending_ids == {second.id}

        # get_pending() (latest row) must return the new one
        latest = ag.get_pending(thread_id)
        assert latest is not None
        assert latest.id == second.id
        assert latest.details["round"] == 2
    finally:
        _cleanup(thread_id)
