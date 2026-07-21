"""Event bus tests — publish/subscribe, per-task ordering, retry, failed handlers."""

from __future__ import annotations

import pytest

from app.event_bus.bus import publish_event, subscribe, unsubscribe, _subscribers
from app.event_bus.models import (
    GridironEvent,
    task_created,
    task_planned,
    qa_passed,
    qa_failed,
    task_blocked,
    CORE_EVENT_TYPES,
)


@pytest.fixture(autouse=True)
def clear_subscribers() -> None:  # type: ignore[return]
    """Ensure each test starts with no subscribers to prevent cross-test pollution."""
    _subscribers.clear()
    yield
    _subscribers.clear()


# ---- Event model tests ----


def test_event_model_defaults() -> None:
    evt = GridironEvent(event_type="task.created")
    assert evt.event_id  # UUID generated
    assert evt.payload == {}
    assert evt.task_id is None


def test_event_model_immutable() -> None:
    evt = GridironEvent(event_type="task.created", task_id="42")
    with pytest.raises(Exception):
        evt.task_id = "99"  # type: ignore[misc]


def test_event_factory_helpers() -> None:
    evt = task_created("42", "Add auth endpoint")
    assert evt.event_type == "task.created"
    assert evt.task_id == "42"
    assert evt.payload["title"] == "Add auth endpoint"

    evt2 = qa_failed("42", 1, ["mypy error: foo"])
    assert evt2.event_type == "qa.failed"
    assert evt2.payload["errors"] == ["mypy error: foo"]


def test_core_event_types_contains_required() -> None:
    required = {
        "task.created",
        "task.planned",
        "subtask.assigned",
        "qa.passed",
        "qa.failed",
        "review.completed",
        "task.blocked",
    }
    assert required.issubset(CORE_EVENT_TYPES)


# ---- Subscribe / unsubscribe tests ----


def test_subscribe_registers_handler() -> None:
    received: list[GridironEvent] = []

    async def handler(event: GridironEvent) -> None:
        received.append(event)

    subscribe("task.created", handler)
    assert handler in _subscribers["task.created"]


def test_subscribe_is_idempotent() -> None:
    async def handler(event: GridironEvent) -> None:
        pass

    subscribe("task.created", handler)
    subscribe("task.created", handler)
    assert _subscribers["task.created"].count(handler) == 1


def test_unsubscribe_removes_handler() -> None:
    async def handler(event: GridironEvent) -> None:
        pass

    subscribe("task.created", handler)
    unsubscribe("task.created", handler)
    assert handler not in _subscribers["task.created"]


def test_unsubscribe_nonexistent_handler_is_noop() -> None:
    async def handler(event: GridironEvent) -> None:
        pass

    unsubscribe("task.created", handler)  # should not raise


# ---- Publish/subscribe roundtrip tests ----


@pytest.mark.asyncio
async def test_publish_dispatches_to_subscriber() -> None:
    received: list[GridironEvent] = []

    async def handler(event: GridironEvent) -> None:
        received.append(event)

    subscribe("task.created", handler)
    evt = task_created("1", "Test task")
    await publish_event(evt, db=None)

    assert len(received) == 1
    assert received[0].event_type == "task.created"
    assert received[0].task_id == "1"


@pytest.mark.asyncio
async def test_publish_only_dispatches_to_matching_event_type() -> None:
    qa_received: list[GridironEvent] = []
    task_received: list[GridironEvent] = []

    async def qa_handler(event: GridironEvent) -> None:
        qa_received.append(event)

    async def task_handler(event: GridironEvent) -> None:
        task_received.append(event)

    subscribe("qa.passed", qa_handler)
    subscribe("task.created", task_handler)

    await publish_event(qa_passed("1", 1), db=None)

    assert len(qa_received) == 1
    assert len(task_received) == 0


@pytest.mark.asyncio
async def test_multiple_subscribers_same_event_type() -> None:
    received_a: list[str] = []
    received_b: list[str] = []

    async def handler_a(event: GridironEvent) -> None:
        received_a.append(event.event_id)

    async def handler_b(event: GridironEvent) -> None:
        received_b.append(event.event_id)

    subscribe("task.planned", handler_a)
    subscribe("task.planned", handler_b)

    evt = task_planned("42", 3)
    await publish_event(evt, db=None)

    assert received_a == [evt.event_id]
    assert received_b == [evt.event_id]


# ---- Per-task ordering test ----


@pytest.mark.asyncio
async def test_events_delivered_in_publish_order_per_task() -> None:
    """Events for the same task are published sequentially (no concurrency) — ordering guaranteed."""
    order: list[str] = []

    async def handler(event: GridironEvent) -> None:
        order.append(event.event_type)

    subscribe("task.created", handler)
    subscribe("task.planned", handler)
    subscribe("subtask.assigned", handler)

    # Publish in order
    await publish_event(task_created("1", "T"), db=None)
    await publish_event(task_planned("1", 2), db=None)
    from app.event_bus.models import subtask_assigned

    await publish_event(subtask_assigned("1", 1, "backend"), db=None)

    assert order == ["task.created", "task.planned", "subtask.assigned"]


# ---- Retry / failure tests ----


@pytest.mark.asyncio
async def test_failing_handler_retried_up_to_max_retries() -> None:
    """A handler that always raises is retried 3 times, then the event is NOT re-raised."""
    call_count = 0

    async def bad_handler(event: GridironEvent) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("simulated failure")

    subscribe("task.blocked", bad_handler)

    # Should not raise even if handler always fails
    await publish_event(task_blocked("1", "test failure"), db=None)

    # Handler was called _MAX_RETRIES times (3)
    assert call_count == 3


@pytest.mark.asyncio
async def test_failing_handler_does_not_block_other_handlers() -> None:
    """If one handler fails, subsequent handlers still receive the event."""
    success_received: list[GridironEvent] = []

    async def bad_handler(event: GridironEvent) -> None:
        raise RuntimeError("I always fail")

    async def good_handler(event: GridironEvent) -> None:
        success_received.append(event)

    subscribe("task.created", bad_handler)
    subscribe("task.created", good_handler)

    await publish_event(task_created("2", "Should reach good handler"), db=None)

    assert len(success_received) == 1


# ---- Sync handler support ----


@pytest.mark.asyncio
async def test_sync_handler_is_accepted() -> None:
    """Sync (non-async) handlers are also dispatched correctly."""
    received: list[str] = []

    def sync_handler(event: GridironEvent) -> None:
        received.append(event.event_type)

    subscribe("qa.passed", sync_handler)
    await publish_event(qa_passed("1", 1), db=None)

    assert received == ["qa.passed"]
