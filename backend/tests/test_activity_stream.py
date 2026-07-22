"""Tests for ActivityStream (Day 5A)."""

from __future__ import annotations


import pytest

from app.services.activity_stream import (
    TaskStream,
    ActivityStreamRegistry,
    push_thinking,
    push_tool_call,
    push_tool_result,
    push_file_edit,
    push_terminal,
    push_token_usage,
    push_done,
    push_stopped,
    push_error,
    push_agent_switch,
    push_approval_required,
)

# ---------------------------------------------------------------------------
# TaskStream
# ---------------------------------------------------------------------------


class TestTaskStream:
    @pytest.mark.asyncio
    async def test_push_and_subscribe(self):
        stream = TaskStream("t1")
        stream.push({"type": "thinking", "content": "hello", "agent": "planner"})
        # Push a done event so subscribe terminates
        stream.push({"type": "done", "result": {}, "ts": 0.0})

        events = []
        async for ev in stream.subscribe(timeout=2.0):
            events.append(ev)

        assert any(e["type"] == "thinking" for e in events)

    def test_abort_flag(self):
        stream = TaskStream("t2")
        assert not stream.should_abort()
        stream.set_abort()
        assert stream.should_abort()

    def test_resume_clears_abort(self):
        stream = TaskStream("t3")
        stream.set_abort()
        stream.set_resume("continue", [])
        assert not stream.should_abort()
        payload = stream.pop_resume()
        assert payload is not None
        assert payload["message"] == "continue"
        assert stream.pop_resume() is None  # consumed

    @pytest.mark.asyncio
    async def test_done_event_terminates_subscribe(self):
        stream = TaskStream("t4")
        stream.push(
            {
                "type": "done",
                "result": {},
                "tokens_in": 10,
                "tokens_out": 5,
                "cost_usd": 0.0,
            }
        )

        events = []
        async for ev in stream.subscribe(timeout=2.0):
            events.append(ev)

        assert events[-1]["type"] == "done"

    def test_push_stamps_task_id_and_ts(self):
        stream = TaskStream("t5")
        event: dict = {"type": "ping"}
        stream.push(event)
        assert event.get("task_id") == "t5"
        assert "ts" in event


# ---------------------------------------------------------------------------
# ActivityStreamRegistry
# ---------------------------------------------------------------------------


class TestActivityStreamRegistry:
    def test_create_and_get(self):
        registry = ActivityStreamRegistry()
        stream = registry.create("r1")
        assert registry.get("r1") is stream

    def test_get_or_create_idempotent(self):
        registry = ActivityStreamRegistry()
        s1 = registry.get_or_create("r2")
        s2 = registry.get_or_create("r2")
        assert s1 is s2

    def test_remove(self):
        registry = ActivityStreamRegistry()
        registry.create("r3")
        registry.remove("r3")
        assert registry.get("r3") is None

    def test_set_abort_returns_false_when_missing(self):
        registry = ActivityStreamRegistry()
        result = registry.set_abort("nonexistent_task_xyz")
        assert result is False

    def test_set_abort_sets_flag(self):
        registry = ActivityStreamRegistry()
        registry.create("r4")
        assert registry.set_abort("r4") is True
        assert registry.should_abort("r4")

    def test_push_event_noop_when_missing(self):
        registry = ActivityStreamRegistry()
        # Should not raise
        registry.push_event("not_a_task", {"type": "ping"})


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


class TestConvenienceHelpers:
    """Integration: helpers create events in a real TaskStream."""

    def setup_method(self):
        import app.services.activity_stream as _mod

        # Use fresh registry for isolation
        self.reg = ActivityStreamRegistry()
        self.reg.create("h1")
        self._orig = _mod._registry
        _mod._registry = self.reg

    def teardown_method(self):
        import app.services.activity_stream as _mod

        _mod._registry = self._orig

    def _drain(self, task_id: str) -> list[dict]:
        stream = self.reg.get(task_id)
        assert stream is not None
        events = []
        while not stream._queue.empty():
            events.append(stream._queue.get_nowait())
        return events

    def test_push_thinking(self):
        push_thinking("h1", "I am thinking", "planner")
        evs = self._drain("h1")
        assert evs[0]["type"] == "thinking"
        assert evs[0]["agent"] == "planner"
        assert evs[0]["content"] == "I am thinking"

    def test_push_tool_call(self):
        push_tool_call("h1", "write_file", {"path": "foo.py"}, "tc_1")
        evs = self._drain("h1")
        assert evs[0]["type"] == "tool_call"
        assert evs[0]["tool"] == "write_file"
        assert evs[0]["id"] == "tc_1"

    def test_push_tool_result(self):
        push_tool_result("h1", "write_file", "ok", True, "tc_1")
        evs = self._drain("h1")
        assert evs[0]["type"] == "tool_result"
        assert evs[0]["ok"] is True

    def test_push_file_edit(self):
        push_file_edit("h1", "/repo/app/foo.py", "write_file")
        evs = self._drain("h1")
        assert evs[0]["type"] == "file_edit"
        assert evs[0]["path"] == "/repo/app/foo.py"

    def test_push_terminal(self):
        push_terminal("h1", "pytest tests/", "5 passed", 0)
        evs = self._drain("h1")
        assert evs[0]["type"] == "terminal"
        assert evs[0]["exit_code"] == 0

    def test_push_token_usage(self):
        push_token_usage("h1", 1000, 200)
        evs = self._drain("h1")
        assert evs[0]["type"] == "token_usage"
        assert evs[0]["tokens_in"] == 1000
        assert evs[0]["cost_usd"] > 0

    def test_push_done(self):
        push_done("h1", {"summary": "done"}, 500, 100)
        evs = self._drain("h1")
        assert evs[0]["type"] == "done"
        assert evs[0]["summary"] == "done"

    def test_push_stopped(self):
        push_stopped("h1", "ckpt_abc", 400, 80)
        evs = self._drain("h1")
        assert evs[0]["type"] == "stopped"
        assert evs[0]["checkpoint_id"] == "ckpt_abc"

    def test_push_error(self):
        push_error("h1", "Something went wrong")
        evs = self._drain("h1")
        assert evs[0]["type"] == "error"
        assert "wrong" in evs[0]["message"]

    def test_push_agent_switch(self):
        """Day 18 — documented in this module's own docstring since it was
        written ("agent_switch — role_name changed mid-pipeline") but never
        implemented until now."""
        push_agent_switch("h1", "architect", "planning")
        evs = self._drain("h1")
        assert evs[0]["type"] == "agent_switch"
        assert evs[0]["agent"] == "architect"
        assert evs[0]["phase"] == "planning"

    def test_push_approval_required(self):
        push_approval_required("h1", "task-1", "plan_review")
        evs = self._drain("h1")
        assert evs[0]["type"] == "approval_required"
        assert evs[0]["thread_id"] == "task-1"
        assert evs[0]["action"] == "plan_review"


# ---------------------------------------------------------------------------
# Heartbeat interval (Day 18 — plan's own success criterion: "heartbeat
# tested with 16s wait"). Uses a short custom timeout rather than a real 16s
# sleep to keep the suite fast, proving the ping mechanism itself works —
# the actual 15.0 interval used in production is asserted directly against
# app/api/activity.py's source below.
# ---------------------------------------------------------------------------


class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_ping_fires_after_timeout_when_queue_empty(self):
        stream = TaskStream("hb1")
        events = []
        async for ev in stream.subscribe(timeout=0.05):
            events.append(ev)
            if len(events) == 2:
                break
        assert all(e["type"] == "ping" for e in events)

    def test_stream_endpoint_uses_15_second_heartbeat(self):
        """Day 18 — the plan's own success criterion ("heartbeat tested with
        16s wait") requires an interval <= 16s; the previous 30s meant a 16s
        wait could never observe one. Asserts the real production value,
        not a re-implementation of it."""
        import inspect

        from app.api import activity

        source = inspect.getsource(activity.stream_task_events)
        assert "timeout=15.0" in source
