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


def task_created(
    task_id: str, title: str, agent_name: str = "", trace_id: str = ""
) -> FleetEvent:
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


def task_completed(
    task_id: str, agent_name: str, summary: str = "", trace_id: str = ""
) -> FleetEvent:
    return FleetEvent(
        event_type=FleetEventType.TASK_COMPLETED,
        task_id=task_id,
        agent_name=agent_name,
        trace_id=trace_id,
        payload={"summary": summary},
    )


def task_failed(
    task_id: str, agent_name: str, reason: str, trace_id: str = ""
) -> FleetEvent:
    return FleetEvent(
        event_type=FleetEventType.TASK_FAILED,
        task_id=task_id,
        agent_name=agent_name,
        trace_id=trace_id,
        payload={"reason": reason},
    )


def review_requested(
    task_id: str, agent_name: str, review_type: str = "", trace_id: str = ""
) -> FleetEvent:
    return FleetEvent(
        event_type=FleetEventType.REVIEW_REQUESTED,
        task_id=task_id,
        agent_name=agent_name,
        trace_id=trace_id,
        payload={"review_type": review_type},
    )


def lesson_published(
    agent_name: str, lesson: str, category: str = "", trace_id: str = ""
) -> FleetEvent:
    return FleetEvent(
        event_type=FleetEventType.LESSON_PUBLISHED,
        agent_name=agent_name,
        trace_id=trace_id,
        payload={"lesson": lesson, "category": category},
    )


def health_updated(
    agent_name: str, health: str, state: str, trace_id: str = ""
) -> FleetEvent:
    return FleetEvent(
        event_type=FleetEventType.HEALTH_UPDATED,
        agent_name=agent_name,
        trace_id=trace_id,
        payload={"health": health, "state": state},
    )


def memory_created(
    agent_name: str, memory_key: str, category: str = "", trace_id: str = ""
) -> FleetEvent:
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


# ---------------------------------------------------------------------------
# Main-loop capture (Audit 01 gap-closure, 2026-07-24)
#
# publish() is called from two very different execution contexts:
#   1. Directly inside an async function already running on the app's main
#      event loop (e.g. manager.py's run_manager/run_epic_manager).
#   2. From inside run_agent_graph() (base_graph.py), which every real agent
#      dispatch path (launch_coder -> run_coder, run_manager's dev/qa/review
#      dispatch -> run_backend_dev/run_frontend_dev/run_qa/run_reviewer) runs
#      via asyncio.to_thread() — a plain ThreadPoolExecutor worker thread that
#      never has an event loop of its own.
#
# The previous implementation called asyncio.get_event_loop(), which raises
# RuntimeError in case 2 (silently swallowed below), meaning the forward to
# the legacy event bus never fired for the large majority of real Fleet OS
# events. Capturing the real main loop once at FastAPI startup (main.py's
# lifespan, which runs on that loop) and scheduling onto it with
# run_coroutine_threadsafe works correctly from any thread, covering both
# contexts uniformly.
# ---------------------------------------------------------------------------

_main_loop: Any = None


def set_main_loop(loop: Any) -> None:
    """Record the app's main event loop. Call once from FastAPI lifespan
    startup, on that loop, before any agent run can publish an event."""
    global _main_loop
    _main_loop = loop


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
                payload={
                    **event.payload,
                    "fleet_trace_id": event.trace_id,
                    "fleet_event_type": event.event_type.value,
                },
                emitted_by=event.agent_name or "fleet_os",
            )

            # Preferred path: a real main loop was captured at startup.
            # run_coroutine_threadsafe works correctly regardless of which
            # thread calls publish() from (worker thread or the loop itself).
            if _main_loop is not None and _main_loop.is_running():
                asyncio.run_coroutine_threadsafe(publish_event(legacy), _main_loop)
                return

            # Fallback for contexts where the app lifespan never ran (e.g. a
            # test that calls publish() directly inside its own async test
            # function) — schedule on the currently-running loop, if any.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(publish_event(legacy))
        except Exception:
            pass


_fleet_bus = FleetBus()


def get_fleet_bus() -> FleetBus:
    return _fleet_bus


def publish(event: FleetEvent) -> None:
    _fleet_bus.publish(event)
