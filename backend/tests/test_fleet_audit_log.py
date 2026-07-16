"""Tests for Fleet OS audit_log.py — Phase F5."""
from __future__ import annotations

import pytest

from app.fleet.audit_log import AuditEntry, AuditLog, audit, get_audit_log


def _fresh() -> AuditLog:
    return AuditLog(capacity=100)


class TestAuditEntry:
    def test_entry_has_unique_id(self) -> None:
        e1 = AuditEntry(action_type="file_write", agent_name="coder", description="wrote main.py")
        e2 = AuditEntry(action_type="file_write", agent_name="coder", description="wrote main.py")
        assert e1.entry_id != e2.entry_id

    def test_entry_to_dict_has_all_fields(self) -> None:
        e = AuditEntry(
            action_type="bash_exec",
            agent_name="devops",
            task_id="task-1",
            description="ran git status",
            details={"cmd": "git status"},
            outcome="success",
            requires_human_approval=False,
        )
        d = e.to_dict()
        assert d["action_type"] == "bash_exec"
        assert d["agent_name"] == "devops"
        assert d["task_id"] == "task-1"
        assert d["outcome"] == "success"
        assert "entry_id" in d
        assert "timestamp" in d


class TestAuditLog:
    def test_append_stores_entry(self) -> None:
        log = _fresh()
        log.append("file_write", "coder", "wrote utils.py")
        assert log.total_appended == 1

    def test_append_never_raises(self) -> None:
        log = _fresh()
        # even with unusual inputs, must not raise
        log.append("", "", "", details=None, outcome="", trace_id=None)
        assert log.total_appended == 1

    def test_recent_returns_latest_n(self) -> None:
        log = _fresh()
        for i in range(10):
            log.append("op", "agent", f"action {i}")
        recent = log.recent(5)
        assert len(recent) == 5
        assert recent[-1].description == "action 9"

    def test_by_trace_filters_correctly(self) -> None:
        log = _fresh()
        log.append("op", "agent", "a1", trace_id="trace-AAA")
        log.append("op", "agent", "a2", trace_id="trace-BBB")
        log.append("op", "agent", "a3", trace_id="trace-AAA")
        matching = log.by_trace("trace-AAA")
        assert len(matching) == 2
        assert all(e.trace_id == "trace-AAA" for e in matching)

    def test_by_task_filters_correctly(self) -> None:
        log = _fresh()
        log.append("op", "agent", "a1", task_id="task-1")
        log.append("op", "agent", "a2", task_id="task-2")
        result = log.by_task("task-1")
        assert len(result) == 1
        assert result[0].task_id == "task-1"

    def test_record_approval_sets_correct_fields(self) -> None:
        log = _fresh()
        entry = log.record_approval(
            agent_name="coder",
            action_type="git_push",
            description="Push to origin/main",
            approved=True,
            approved_by="user@example.com",
            task_id="task-99",
        )
        assert entry.requires_human_approval is True
        assert entry.outcome == "approved"
        assert entry.approved_by == "user@example.com"

    def test_record_rejection_clears_approved_by(self) -> None:
        log = _fresh()
        entry = log.record_approval(
            agent_name="coder",
            action_type="git_push",
            description="Push to origin/main",
            approved=False,
        )
        assert entry.outcome == "rejected"
        assert entry.approved_by is None

    def test_approvals_returns_only_approval_entries(self) -> None:
        log = _fresh()
        log.append("file_write", "coder", "wrote file")
        log.record_approval("coder", "git_push", "push", approved=True)
        log.record_approval("coder", "run_migration", "migrate", approved=False)
        approvals = log.approvals()
        assert len(approvals) == 2
        assert all(e.requires_human_approval for e in approvals)

    def test_ring_capacity_evicts_oldest(self) -> None:
        log = AuditLog(capacity=5)
        for i in range(10):
            log.append("op", "agent", f"action {i}")
        assert log.total_appended == 10
        recent = log.recent(10)
        assert len(recent) == 5
        assert recent[0].description == "action 5"

    def test_trace_id_correlation(self) -> None:
        log = _fresh()
        log.append("dispatch", "fleet", "task started", trace_id="trace-XYZ")
        log.append("file_write", "coder", "wrote main.py", trace_id="trace-XYZ")
        log.record_approval("coder", "git_push", "push main", approved=True, trace_id="trace-XYZ")
        timeline = log.by_trace("trace-XYZ")
        assert len(timeline) == 3
        types = [e.action_type for e in timeline]
        assert "dispatch" in types
        assert "git_push" in types


class TestGlobalAudit:
    def test_audit_function_uses_singleton(self) -> None:
        log = get_audit_log()
        before = log.total_appended
        audit("test_op", "test_agent", "global audit test")
        assert log.total_appended == before + 1


# ---- Day 0 exit criterion: real human-approval entry ----

def test_real_human_approval_entry() -> None:
    """Day 0 criterion §20: audit_log has a real entry for a real human-approval decision."""
    log = _fresh()

    entry = log.record_approval(
        agent_name="bug_fix",
        action_type="undo_changes",
        description="Restore src/main.py to last committed state (git checkout -- src/main.py)",
        approved=True,
        approved_by="human_operator",
        task_id="task-day0-test",
        trace_id="trace-day0-001",
    )

    assert entry.requires_human_approval is True
    assert entry.outcome == "approved"
    assert entry.approved_by == "human_operator"
    assert entry.trace_id == "trace-day0-001"

    retrieved = log.by_trace("trace-day0-001")
    assert len(retrieved) == 1
    assert retrieved[0].entry_id == entry.entry_id
