"""Event schemas — typed Pydantic models for every event type in the bus."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class GridironEvent(BaseModel):
    """Core event envelope. Every event in the bus uses this schema."""

    event_id: str = Field(default_factory=_new_uuid)
    event_type: str
    task_id: str | None = None
    epic_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    emitted_by: str = ""
    created_at: datetime = Field(default_factory=_now_utc)

    # plan14 Day 4 (#12 Agent Communication) — extends this existing,
    # already-universal envelope for delegation-relevant routing/tracing
    # instead of building a second, competing message schema (AutoGen's
    # separate AgentId/envelope system was considered and rejected for
    # exactly that reason — see app/agents/delegation.py's own module
    # docstring). All optional, defaulted None — every existing event
    # construction call site (task_created, qa_passed, ...) is unaffected.
    receiver: str | None = None
    message_type: str | None = None
    trace_id: str | None = None
    parent_run_id: str | None = None

    model_config = {"frozen": True}


# ---- Typed payload helpers (not enforced at runtime — docs for callers) ----

CORE_EVENT_TYPES = frozenset(
    {
        "task.created",
        "task.planned",
        "architecture.ready",
        "subtask.assigned",
        "qa.passed",
        "qa.failed",
        "review.completed",
        "epic.completed",
        "task.blocked",
        # Phase 5 epic lifecycle events
        "epic.pending_cost_approval",
        "epic.planning_started",
        "epic.ready_for_review",
        "epic.halted",
        "epic.approved",
        "epic.rejected",
        # plan14 Day 4 (#1/#13/#12) — delegation lifecycle
        "delegation.requested",
        "delegation.started",
        "delegation.completed",
        "delegation.failed",
    }
)


def delegation_requested(
    *,
    source_agent: str,
    target_capability: str,
    trace_id: str,
    parent_run_id: str,
    task_id: str | None = None,
) -> GridironEvent:
    return GridironEvent(
        event_type="delegation.requested",
        task_id=task_id,
        payload={"source_agent": source_agent, "target_capability": target_capability},
        emitted_by=source_agent,
        receiver=target_capability,
        message_type="delegation_requested",
        trace_id=trace_id,
        parent_run_id=parent_run_id,
    )


def delegation_started(
    *,
    source_agent: str,
    target_agent: str,
    trace_id: str,
    parent_run_id: str,
    task_id: str | None = None,
) -> GridironEvent:
    return GridironEvent(
        event_type="delegation.started",
        task_id=task_id,
        payload={"source_agent": source_agent, "target_agent": target_agent},
        emitted_by=source_agent,
        receiver=target_agent,
        message_type="delegation_started",
        trace_id=trace_id,
        parent_run_id=parent_run_id,
    )


def delegation_completed(
    *,
    source_agent: str,
    target_agent: str,
    trace_id: str,
    parent_run_id: str,
    cost_usd: float,
    task_id: str | None = None,
) -> GridironEvent:
    return GridironEvent(
        event_type="delegation.completed",
        task_id=task_id,
        payload={
            "source_agent": source_agent,
            "target_agent": target_agent,
            "cost_usd": cost_usd,
        },
        emitted_by=target_agent,
        receiver=source_agent,
        message_type="delegation_completed",
        trace_id=trace_id,
        parent_run_id=parent_run_id,
    )


def delegation_failed(
    *,
    source_agent: str,
    target_agent: str | None,
    trace_id: str,
    parent_run_id: str,
    reason: str,
    task_id: str | None = None,
) -> GridironEvent:
    return GridironEvent(
        event_type="delegation.failed",
        task_id=task_id,
        payload={
            "source_agent": source_agent,
            "target_agent": target_agent,
            "reason": reason,
        },
        emitted_by=target_agent or source_agent,
        receiver=source_agent,
        message_type="delegation_failed",
        trace_id=trace_id,
        parent_run_id=parent_run_id,
    )


def task_created(
    task_id: str, title: str, emitted_by: str = "task_engine"
) -> GridironEvent:
    return GridironEvent(
        event_type="task.created",
        task_id=task_id,
        payload={"title": title},
        emitted_by=emitted_by,
    )


def task_planned(
    task_id: str, subtask_count: int, emitted_by: str = "decomposer"
) -> GridironEvent:
    return GridironEvent(
        event_type="task.planned",
        task_id=task_id,
        payload={"subtask_count": subtask_count},
        emitted_by=emitted_by,
    )


def architecture_ready(
    task_id: str, impacted_files: list[str], emitted_by: str = "architect"
) -> GridironEvent:
    return GridironEvent(
        event_type="architecture.ready",
        task_id=task_id,
        payload={"impacted_files": impacted_files},
        emitted_by=emitted_by,
    )


def subtask_assigned(
    task_id: str, subtask_id: int, subtask_type: str, emitted_by: str = "manager"
) -> GridironEvent:
    return GridironEvent(
        event_type="subtask.assigned",
        task_id=task_id,
        payload={"subtask_id": subtask_id, "type": subtask_type},
        emitted_by=emitted_by,
    )


def qa_passed(task_id: str, subtask_id: int, emitted_by: str = "qa") -> GridironEvent:
    return GridironEvent(
        event_type="qa.passed",
        task_id=task_id,
        payload={"subtask_id": subtask_id},
        emitted_by=emitted_by,
    )


def qa_failed(
    task_id: str, subtask_id: int, errors: list[str], emitted_by: str = "qa"
) -> GridironEvent:
    return GridironEvent(
        event_type="qa.failed",
        task_id=task_id,
        payload={"subtask_id": subtask_id, "errors": errors[:3]},
        emitted_by=emitted_by,
    )


def review_completed(
    task_id: str, subtask_id: int, verdict: str, emitted_by: str = "reviewer"
) -> GridironEvent:
    return GridironEvent(
        event_type="review.completed",
        task_id=task_id,
        payload={"subtask_id": subtask_id, "verdict": verdict},
        emitted_by=emitted_by,
    )


def task_blocked(
    task_id: str, reason: str, emitted_by: str = "manager"
) -> GridironEvent:
    return GridironEvent(
        event_type="task.blocked",
        task_id=task_id,
        payload={"reason": reason},
        emitted_by=emitted_by,
    )
