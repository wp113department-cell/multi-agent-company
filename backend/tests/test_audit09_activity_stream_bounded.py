"""Production audit 09 (2026-10-02): the activity-stream registry is bounded.

Before: every TaskStream (up to 500 events of history each) stayed in memory
for the life of the process, one per task ever run or subscribed to.
"""

from __future__ import annotations

import time

import pytest

from app.services import activity_stream
from app.services.activity_stream import ActivityStreamRegistry


@pytest.fixture()
def small_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(activity_stream, "_MAX_STREAMS", 3)


def test_finished_streams_are_evicted_past_the_cap(small_cap: None) -> None:
    reg = ActivityStreamRegistry()
    for i in range(10):
        reg.get_or_create(f"a09-done-{i}").push({"type": "done"})
    assert len(reg._streams) <= 3 + 1
    assert reg.get("a09-done-9") is not None, "newest stream must survive"


def test_running_and_subscribed_streams_are_kept(small_cap: None) -> None:
    reg = ActivityStreamRegistry()
    running = reg.get_or_create("a09-running")
    running.push({"type": "tool_call"})
    watched = reg.get_or_create("a09-watched")
    watched.push({"type": "done"})
    watched._subscriber_queues.append(object())  # type: ignore[arg-type]
    for i in range(10):
        reg.get_or_create(f"a09-fill-{i}").push({"type": "done"})
    assert reg.get("a09-running") is running
    assert reg.get("a09-watched") is watched


def test_long_idle_unfinished_stream_is_evicted(small_cap: None) -> None:
    reg = ActivityStreamRegistry()
    idle = reg.get_or_create("a09-idle")
    idle.last_activity = time.monotonic() - activity_stream._IDLE_EVICT_SECONDS - 1
    for i in range(5):
        reg.get_or_create(f"a09-live-{i}").push({"type": "tool_call"})
    assert reg.get("a09-idle") is None
