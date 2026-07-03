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

    model_config = {"frozen": True}


# ---- Typed payload helpers (not enforced at runtime — docs for callers) ----

CORE_EVENT_TYPES = frozenset({
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
})


def task_created(task_id: str, title: str, emitted_by: str = "task_engine") -> GridironEvent:
    return GridironEvent(event_type="task.created", task_id=task_id, payload={"title": title}, emitted_by=emitted_by)


def task_planned(task_id: str, subtask_count: int, emitted_by: str = "decomposer") -> GridironEvent:
    return GridironEvent(event_type="task.planned", task_id=task_id, payload={"subtask_count": subtask_count}, emitted_by=emitted_by)


def architecture_ready(task_id: str, impacted_files: list[str], emitted_by: str = "architect") -> GridironEvent:
    return GridironEvent(event_type="architecture.ready", task_id=task_id, payload={"impacted_files": impacted_files}, emitted_by=emitted_by)


def subtask_assigned(task_id: str, subtask_id: int, subtask_type: str, emitted_by: str = "manager") -> GridironEvent:
    return GridironEvent(
        event_type="subtask.assigned",
        task_id=task_id,
        payload={"subtask_id": subtask_id, "type": subtask_type},
        emitted_by=emitted_by,
    )


def qa_passed(task_id: str, subtask_id: int, emitted_by: str = "qa") -> GridironEvent:
    return GridironEvent(event_type="qa.passed", task_id=task_id, payload={"subtask_id": subtask_id}, emitted_by=emitted_by)


def qa_failed(task_id: str, subtask_id: int, errors: list[str], emitted_by: str = "qa") -> GridironEvent:
    return GridironEvent(event_type="qa.failed", task_id=task_id, payload={"subtask_id": subtask_id, "errors": errors[:3]}, emitted_by=emitted_by)


def review_completed(task_id: str, subtask_id: int, verdict: str, emitted_by: str = "reviewer") -> GridironEvent:
    return GridironEvent(event_type="review.completed", task_id=task_id, payload={"subtask_id": subtask_id, "verdict": verdict}, emitted_by=emitted_by)


def task_blocked(task_id: str, reason: str, emitted_by: str = "manager") -> GridironEvent:
    return GridironEvent(event_type="task.blocked", task_id=task_id, payload={"reason": reason}, emitted_by=emitted_by)
