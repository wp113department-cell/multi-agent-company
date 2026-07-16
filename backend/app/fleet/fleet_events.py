"""Fleet OS typed event overlay — §6 of Master Prompt v4.

Architecture Decision: Backward-Compatible Overlay (see docs/adr/ADR-001)

DO NOT modify, replace, or remove any existing event types in event_bus/models.py.
This module adds the 8 Fleet OS typed events as a SEPARATE layer on top of the
existing bus. Both coexist. Neither breaks the other.

The 8 Fleet OS event types (§6):
  TaskCreated, TaskStarted, TaskCompleted, TaskFailed,
  ReviewRequested, LessonPublished, HealthUpdated, MemoryCreated

Fleet OS agents publish and consume these events.
Legacy agents continue using CORE_EVENT_TYPES from event_bus/models.py unchanged.

Bidirectional mapping:
  Legacy → Fleet OS  (used when a legacy event should trigger Fleet OS logic)
  Fleet OS → Legacy  (used when Fleet OS events should flow to legacy subscribers)

Migration rule: do not remove a legacy event type until ALL agents that publish
  or subscribe to it have been migrated and verified.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Fleet OS typed event protocol
# ---------------------------------------------------------------------------

class FleetEventType(str, Enum):
    TASK_CREATED = "TaskCreated"
    TASK_STARTED = "TaskStarted"
    TASK_COMPLETED = "TaskCompleted"
    TASK_FAILED = "TaskFailed"
    REVIEW_REQUESTED = "ReviewRequested"
    LESSON_PUBLISHED = "LessonPublished"
    HEALTH_UPDATED = "HealthUpdated"
    MEMORY_CREATED = "MemoryCreated"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class FleetEvent(BaseModel):
    """Typed event envelope for Fleet OS. Immutable after creation."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: FleetEventType
    task_id: str | None = None
    agent_name: str = ""
    trace_id: str = ""
    timestamp: datetime = Field(default_factory=_now_utc)
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Typed constructors (one per event type — prevents ad-hoc dict creation)
# ---------------------------------------------------------------------------

def task_created(task_id: str, title: str, agent_name: str = "", trace_id: str = "") -> FleetEvent:
    return FleetEvent(
        event_type=FleetEventType.TASK_CREATED,
        task_id=task_id,
        agent_name=agent_name,
        trace_id=trace_id,
        payload={"title": title},
    )


def task_started(task_id: str, agent_name: str, trace_id: str = "") -> FleetEvent:
    return FleetEvent(
        event_type=FleetEventType.TASK_STARTED,
        task_id=task_id,
        agent_name=agent_name,
        trace_id=trace_id,
        payload={"agent": agent_name},
    )


def task_completed(task_id: str, agent_name: str, summary: str = "", trace_id: str = "") -> FleetEvent:
    return FleetEvent(
        event_type=FleetEventType.TASK_COMPLETED,
        task_id=task_id,
        agent_name=agent_name,
        trace_id=trace_id,
        payload={"summary": summary},
    )


def task_failed(task_id: str, agent_name: str, reason: str, trace_id: str = "") -> FleetEvent:
    return FleetEvent(
        event_type=FleetEventType.TASK_FAILED,
        task_id=task_id,
        agent_name=agent_name,
        trace_id=trace_id,
        payload={"reason": reason},
    )


def review_requested(task_id: str, agent_name: str, review_type: str = "", trace_id: str = "") -> FleetEvent:
    return FleetEvent(
        event_type=FleetEventType.REVIEW_REQUESTED,
        task_id=task_id,
        agent_name=agent_name,
        trace_id=trace_id,
        payload={"review_type": review_type},
    )


def lesson_published(agent_name: str, lesson: str, category: str = "", trace_id: str = "") -> FleetEvent:
    return FleetEvent(
        event_type=FleetEventType.LESSON_PUBLISHED,
        agent_name=agent_name,
        trace_id=trace_id,
        payload={"lesson": lesson, "category": category},
    )


def health_updated(agent_name: str, health: str, state: str, trace_id: str = "") -> FleetEvent:
    return FleetEvent(
        event_type=FleetEventType.HEALTH_UPDATED,
        agent_name=agent_name,
        trace_id=trace_id,
        payload={"health": health, "state": state},
    )


def memory_created(agent_name: str, memory_key: str, category: str = "", trace_id: str = "") -> FleetEvent:
    return FleetEvent(
        event_type=FleetEventType.MEMORY_CREATED,
        agent_name=agent_name,
        trace_id=trace_id,
        payload={"memory_key": memory_key, "category": category},
    )


# ---------------------------------------------------------------------------
# Bidirectional mapping — legacy ↔ Fleet OS
# ---------------------------------------------------------------------------

# Legacy event_type string → nearest Fleet OS event type
# Purpose: Fleet OS subscribers that want to react to legacy events can do so
#          without requiring the legacy agents to be migrated.
LEGACY_TO_FLEET: dict[str, FleetEventType] = {
    "task.created": FleetEventType.TASK_CREATED,
    "task.planned": FleetEventType.TASK_STARTED,
    "epic.planning_started": FleetEventType.TASK_STARTED,
    "subtask.assigned": FleetEventType.TASK_STARTED,
    "epic.completed": FleetEventType.TASK_COMPLETED,
    "epic.ready_for_review": FleetEventType.TASK_COMPLETED,
    "task.blocked": FleetEventType.TASK_FAILED,
    "epic.halted": FleetEventType.TASK_FAILED,
    "review.completed": FleetEventType.REVIEW_REQUESTED,
    "qa.passed": FleetEventType.TASK_COMPLETED,
    "qa.failed": FleetEventType.TASK_FAILED,
}

# Fleet OS event type → legacy event_type string to emit for backward compat
# Purpose: When Fleet OS emits a typed event, also emit the legacy event so
#          existing subscribers (e.g., SSE push, metrics handlers) still work.
FLEET_TO_LEGACY: dict[FleetEventType, str] = {
    FleetEventType.TASK_CREATED: "task.created",
    FleetEventType.TASK_STARTED: "task.planned",
    FleetEventType.TASK_COMPLETED: "epic.completed",
    FleetEventType.TASK_FAILED: "task.blocked",
    FleetEventType.REVIEW_REQUESTED: "review.completed",
}


def translate_legacy_to_fleet(legacy_event_type: str) -> FleetEventType | None:
    """Return the Fleet OS event type for a legacy event type, or None if unmapped."""
    return LEGACY_TO_FLEET.get(legacy_event_type)


def translate_fleet_to_legacy(fleet_event_type: FleetEventType) -> str | None:
    """Return the legacy event type for a Fleet OS event, or None if no mapping."""
    return FLEET_TO_LEGACY.get(fleet_event_type)


# ---------------------------------------------------------------------------
# Fleet OS bus (thin wrapper — publishes to existing bus AND records trace)
# ---------------------------------------------------------------------------

class FleetBus:
    """Overlay bus that publishes Fleet OS typed events while also forwarding
    to the existing event_bus so legacy subscribers receive them.
    """

    def publish(self, event: FleetEvent) -> None:
        self._publish_to_existing_bus(event)

    def _publish_to_existing_bus(self, event: FleetEvent) -> None:
        legacy_type = translate_fleet_to_legacy(event.event_type)
        if legacy_type is None:
            return

        try:
            import asyncio
            from app.event_bus.bus import publish_event
            from app.event_bus.models import GridironEvent

            legacy = GridironEvent(
                event_type=legacy_type,
                task_id=event.task_id,
                payload={**event.payload, "fleet_trace_id": event.trace_id, "fleet_event_type": event.event_type.value},
                emitted_by=event.agent_name or "fleet_os",
            )

            loop = None
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                pass

            if loop and loop.is_running():
                asyncio.create_task(publish_event(legacy))
        except Exception:
            pass


_fleet_bus = FleetBus()


def get_fleet_bus() -> FleetBus:
    return _fleet_bus


def publish(event: FleetEvent) -> None:
    _fleet_bus.publish(event)
