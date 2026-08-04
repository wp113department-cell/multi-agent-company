"""Stage 3, Day 62 (PLAN.md) — "Frontend behavior under real concurrent
load/multiple sessions."

This is a real bug found by measurement, not a pre-existing NOT VERIFIED
item converted to YES: `TaskStream` (`app/services/activity_stream.py`)
used a single shared `asyncio.Queue`, so two concurrent `subscribe()` calls
on the same stream were competing consumers, not independent fan-out
subscribers. Reproduced directly before any fix was written: pushing 6
events to a stream with 2 active subscribers delivered events 0-2 to
subscriber A and 3-5 to subscriber B — never all 6 to both. Any real
"multiple sessions" scenario hits this:
  - Two browser tabs open on the same task's `/stream/[taskId]` activity
    feed (`apps/web/app/stream/[taskId]/page.tsx`'s `EventSource` against
    `GET /api/tasks/{id}/stream`, `app/api/activity.py`).
  - Two people viewing the fleet dashboard's live feed simultaneously
    (`app/api/fleet_dashboard.py`'s single `_DASHBOARD_STREAM_KEY` stream —
    inherently shared across every viewer, not per-task).

Fixed in `app/services/activity_stream.py`: each `subscribe()` call now
gets its own queue (real fan-out via `push()` broadcasting to every live
subscriber queue), with a bounded history replay so a subscriber that joins
after some events were already pushed still sees them — preserving the
pre-existing single-subscriber-arrives-late behavior every other test in
`test_activity_stream.py`/`test_day18_streaming_wiring.py`/
`test_gap_stage15_context_condense.py` already depends on (all 39 of those
tests still pass unchanged in behavior, updated only where they reached
into the now-removed private `_queue` attribute directly).
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.activity_stream import ActivityStreamRegistry, TaskStream


async def _collect_until(
    stream: TaskStream, n: int, timeout: float = 2.0
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    async for event in stream.subscribe(timeout=timeout):
        if event["type"] == "ping":
            continue
        events.append(event)
        if len(events) >= n:
            break
    return events


@pytest.mark.asyncio
async def test_two_concurrent_subscribers_each_see_every_event() -> None:
    """The exact scenario measured before the fix: 2 sessions on the same
    stream, 6 events pushed after both are subscribed. Both must see all 6,
    in order — not a competing-consumer split."""
    stream = TaskStream("shared-task")
    session_a = asyncio.create_task(_collect_until(stream, n=6))
    session_b = asyncio.create_task(_collect_until(stream, n=6))
    await asyncio.sleep(0.05)  # let both subscribe() calls register first

    for i in range(6):
        stream.push({"type": "tool_call", "tool": f"t{i}"})

    received_a, received_b = await asyncio.wait_for(
        asyncio.gather(session_a, session_b), timeout=3.0
    )

    assert [e["tool"] for e in received_a] == [f"t{i}" for i in range(6)]
    assert [e["tool"] for e in received_b] == [f"t{i}" for i in range(6)]


@pytest.mark.asyncio
async def test_late_joining_subscriber_still_sees_events_pushed_before_it_joined() -> (
    None
):
    """The pre-existing single-subscriber behavior every other test in this
    suite already relies on (push-then-subscribe) must still hold for the
    fan-out design — a subscriber joining after the fact replays history
    instead of missing everything that already happened."""
    stream = TaskStream("late-joiner-task")
    stream.push({"type": "tool_call", "tool": "before_anyone_subscribed"})

    events = await _collect_until(stream, n=1)
    assert events[0]["tool"] == "before_anyone_subscribed"


@pytest.mark.asyncio
async def test_twenty_concurrent_sessions_under_load_each_get_the_full_stream() -> None:
    """'Real concurrent load', not just 2 sessions: 20 simultaneous
    subscribers (a plausible real number of concurrent dashboard/activity-
    feed viewers) must each independently receive all 25 pushed events,
    with zero cross-session leakage or drops, within a bounded time."""
    stream = TaskStream("load-task")
    n_sessions = 20
    n_events = 25

    sessions = [
        asyncio.create_task(_collect_until(stream, n=n_events))
        for _ in range(n_sessions)
    ]
    await asyncio.sleep(0.05)

    for i in range(n_events):
        stream.push({"type": "tool_call", "tool": f"e{i}"})

    results = await asyncio.wait_for(asyncio.gather(*sessions), timeout=5.0)

    expected = [f"e{i}" for i in range(n_events)]
    for i, received in enumerate(results):
        assert [
            e["tool"] for e in received
        ] == expected, f"session {i} did not receive the full, correctly-ordered stream"


@pytest.mark.asyncio
async def test_a_slow_subscriber_dropping_events_does_not_affect_other_subscribers() -> (
    None
):
    """A subscriber that never drains its queue (e.g. a stalled browser
    tab) must only ever lose events for itself once its own queue fills —
    it must not block or drop events for any other concurrent subscriber,
    since push() iterates a snapshot of queues and per-queue failures are
    isolated."""
    stream = TaskStream("slow-subscriber-task")

    # A subscriber whose queue we never drain, forced to a tiny capacity by
    # pushing far more events than its real per-subscriber queue can hold.
    stalled_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=2)
    stream._subscriber_queues.append(stalled_queue)

    healthy_session = asyncio.create_task(_collect_until(stream, n=10))
    await asyncio.sleep(0.02)

    for i in range(10):
        stream.push({"type": "tool_call", "tool": f"h{i}"})

    received = await asyncio.wait_for(healthy_session, timeout=3.0)
    assert [e["tool"] for e in received] == [f"h{i}" for i in range(10)]


@pytest.mark.asyncio
async def test_dashboard_shared_stream_key_fans_out_to_multiple_dashboard_viewers() -> (
    None
):
    """app/api/fleet_dashboard.py uses one hardcoded `_DASHBOARD_STREAM_KEY`
    across every dashboard viewer (not per-task like activity.py) — the
    clearest real 'multiple sessions on one stream' case in the codebase.
    Proves the registry-level get_or_create() + subscribe() path (the real
    call pattern fleet_dashboard.py uses) exhibits the same fan-out fix."""
    from app.api.fleet_dashboard import _DASHBOARD_STREAM_KEY

    registry = ActivityStreamRegistry()
    stream = registry.get_or_create(_DASHBOARD_STREAM_KEY)

    viewer_1 = asyncio.create_task(_collect_until(stream, n=3))
    viewer_2 = asyncio.create_task(_collect_until(stream, n=3))
    await asyncio.sleep(0.05)

    registry.push_event(_DASHBOARD_STREAM_KEY, {"type": "enhancement_request", "id": 1})
    registry.push_event(_DASHBOARD_STREAM_KEY, {"type": "enhancement_request", "id": 2})
    registry.push_event(_DASHBOARD_STREAM_KEY, {"type": "enhancement_request", "id": 3})

    received_1, received_2 = await asyncio.wait_for(
        asyncio.gather(viewer_1, viewer_2), timeout=3.0
    )
    assert [e["id"] for e in received_1] == [1, 2, 3]
    assert [e["id"] for e in received_2] == [1, 2, 3]
