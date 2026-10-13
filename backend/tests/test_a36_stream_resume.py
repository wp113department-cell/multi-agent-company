"""Sol A36 (2026-10-13): activity events are numbered, and a reconnecting
client gets only what it has not seen.

Before: a reconnect replayed the whole bounded history and the page
appended it again, so every reconnect duplicated the events.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.services.activity_stream import TaskStream


async def _collect(stream: TaskStream, after: int) -> list[dict[str, Any]]:
    out = []
    async for event in stream.subscribe(timeout=0.2, after=after):
        if event.get("type") == "ping":
            break
        out.append(event)
    return out


def test_events_are_numbered_in_order() -> None:
    stream = TaskStream("a36-order")
    for i in range(3):
        stream.push({"type": "thinking", "content": str(i)})
    events = asyncio.run(_collect(stream, after=0))
    assert [e["seq"] for e in events] == [1, 2, 3]


def test_a_reconnect_gets_only_newer_events() -> None:
    stream = TaskStream("a36-resume")
    for i in range(3):
        stream.push({"type": "thinking", "content": str(i)})
    stream.push({"type": "done", "tokens_in": 1, "tokens_out": 1, "cost_usd": 0})
    events = asyncio.run(_collect(stream, after=2))
    assert [e["seq"] for e in events] == [3, 4]


def test_resuming_after_a_stop_does_not_end_at_the_old_stop() -> None:
    # a stopped-then-resumed task's history holds the old "stopped" event;
    # a client that already saw it must not be cut off by the replay
    stream = TaskStream("a36-stopped")
    stream.push(
        {"type": "stopped", "checkpoint_id": "c1", "tokens_in": 0, "tokens_out": 0}
    )
    stream.push({"type": "thinking", "content": "resumed"})
    stream.push({"type": "done", "tokens_in": 1, "tokens_out": 1, "cost_usd": 0})
    events = asyncio.run(_collect(stream, after=1))
    assert [e["type"] for e in events] == ["thinking", "done"]
