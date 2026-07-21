"""Tests for Fleet OS fleet_events.py — backward-compatible overlay (ADR-001).

These tests prove BOTH legacy and Fleet OS events function correctly during transition.
"""
from __future__ import annotations

import pytest

from app.fleet.fleet_events import (
    LEGACY_TO_FLEET,
    FleetBus,
    FleetEventType,
    health_updated,
    lesson_published,
    memory_created,
    publish,
    review_requested,
    task_completed,
    task_created,
    task_failed,
    task_started,
    translate_fleet_to_legacy,
    translate_legacy_to_fleet,
)


class TestFleetEventTypes:
    def test_all_8_event_types_exist(self) -> None:
        required = {
            "TaskCreated", "TaskStarted", "TaskCompleted", "TaskFailed",
            "ReviewRequested", "LessonPublished", "HealthUpdated", "MemoryCreated",
        }
        actual = {e.value for e in FleetEventType}
        assert required == actual, f"Missing types: {required - actual}"

    def test_no_ad_hoc_event_types_beyond_8(self) -> None:
        assert len(list(FleetEventType)) == 8


class TestTypedConstructors:
    def test_task_created(self) -> None:
        e = task_created("task-1", "Build login page", "pm", "trace-abc")
        assert e.event_type == FleetEventType.TASK_CREATED
        assert e.task_id == "task-1"
        assert e.payload["title"] == "Build login page"
        assert e.trace_id == "trace-abc"

    def test_task_started(self) -> None:
        e = task_started("task-1", "bug_fix", "trace-abc")
        assert e.event_type == FleetEventType.TASK_STARTED
        assert e.agent_name == "bug_fix"

    def test_task_completed(self) -> None:
        e = task_completed("task-1", "bug_fix", "Fixed null pointer", "trace-abc")
        assert e.event_type == FleetEventType.TASK_COMPLETED
        assert e.payload["summary"] == "Fixed null pointer"

    def test_task_failed(self) -> None:
        e = task_failed("task-1", "bug_fix", "Timeout after 120s", "trace-abc")
        assert e.event_type == FleetEventType.TASK_FAILED
        assert e.payload["reason"] == "Timeout after 120s"

    def test_review_requested(self) -> None:
        e = review_requested("task-1", "reviewer", "code_review")
        assert e.event_type == FleetEventType.REVIEW_REQUESTED

    def test_lesson_published(self) -> None:
        e = lesson_published("bug_fix", "Always run tests after edit_file", "testing")
        assert e.event_type == FleetEventType.LESSON_PUBLISHED
        assert e.payload["lesson"] == "Always run tests after edit_file"

    def test_health_updated(self) -> None:
        e = health_updated("bug_fix", "healthy", "sleep")
        assert e.event_type == FleetEventType.HEALTH_UPDATED
        assert e.payload["health"] == "healthy"

    def test_memory_created(self) -> None:
        e = memory_created("qa", "pytest_flags_2026", "testing")
        assert e.event_type == FleetEventType.MEMORY_CREATED
        assert e.payload["memory_key"] == "pytest_flags_2026"

    def test_fleet_event_is_immutable(self) -> None:
        e = task_created("task-1", "title")
        with pytest.raises(Exception):
            e.task_id = "mutated"  # type: ignore[misc]

    def test_fleet_event_has_unique_id(self) -> None:
        e1 = task_created("task-1", "t")
        e2 = task_created("task-1", "t")
        assert e1.event_id != e2.event_id


class TestBidirectionalMapping:
    def test_all_defined_legacy_types_have_fleet_mapping(self) -> None:
        for legacy_type, fleet_type in LEGACY_TO_FLEET.items():
            assert isinstance(fleet_type, FleetEventType)

    def test_translate_legacy_to_fleet_task_created(self) -> None:
        assert translate_legacy_to_fleet("task.created") == FleetEventType.TASK_CREATED

    def test_translate_legacy_to_fleet_epic_completed(self) -> None:
        assert translate_legacy_to_fleet("epic.completed") == FleetEventType.TASK_COMPLETED

    def test_translate_legacy_to_fleet_task_blocked(self) -> None:
        assert translate_legacy_to_fleet("task.blocked") == FleetEventType.TASK_FAILED

    def test_translate_legacy_returns_none_for_unknown(self) -> None:
        assert translate_legacy_to_fleet("some.unknown.event") is None

    def test_translate_fleet_to_legacy(self) -> None:
        assert translate_fleet_to_legacy(FleetEventType.TASK_CREATED) == "task.created"
        assert translate_fleet_to_legacy(FleetEventType.TASK_COMPLETED) == "epic.completed"
        assert translate_fleet_to_legacy(FleetEventType.TASK_FAILED) == "task.blocked"

    def test_translate_fleet_to_legacy_none_for_unmapped(self) -> None:
        assert translate_fleet_to_legacy(FleetEventType.LESSON_PUBLISHED) is None


class TestLegacyEventTypesPreserved:
    """Prove that CORE_EVENT_TYPES from the existing event bus are untouched."""

    def test_core_event_types_still_exist_unchanged(self) -> None:
        from app.event_bus.models import CORE_EVENT_TYPES

        required_legacy = {
            "task.created", "task.planned", "architecture.ready", "subtask.assigned",
            "qa.passed", "qa.failed", "review.completed", "epic.completed",
            "task.blocked", "epic.pending_cost_approval", "epic.planning_started",
            "epic.ready_for_review", "epic.halted", "epic.approved", "epic.rejected",
        }
        for event_type in required_legacy:
            assert event_type in CORE_EVENT_TYPES, f"Legacy event {event_type!r} was removed — violation of ADR-001"

    def test_fleet_events_module_does_not_import_replace_legacy(self) -> None:
        import app.fleet.fleet_events as fe
        # The overlay must not redefine CORE_EVENT_TYPES
        assert not hasattr(fe, "CORE_EVENT_TYPES")


class TestFleetBus:
    def test_publish_does_not_raise_without_event_loop(self) -> None:
        bus = FleetBus()
        e = task_completed("task-1", "bug_fix", "done")
        bus.publish(e)  # must not raise even with no running loop

    def test_publish_via_module_function_does_not_raise(self) -> None:
        e = health_updated("qa", "healthy", "sleep")
        publish(e)  # must not raise
