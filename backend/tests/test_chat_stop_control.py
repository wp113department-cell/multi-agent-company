"""UI gap-closure (2026-09-25) — a real Stop control for the interactive
chat panel.

Real gap this closes: before this, the frontend's own AbortController only
cancelled the CLIENT's fetch connection — it never reached the server-side
background task running ChatAgent.run(), so typing/clicking "stop" had no
effect on the agent at all (it kept running, kept spending tokens, kept
calling tools, until it finished on its own).

Proven directly against the real compiled graph
(app.agents.chat_agent.ChatAgent._graph), same pattern as
test_phase52_chat_graph_interrupt.py: a fake Anthropic streaming client
drives real graph node execution — ChatAgent.request_stop() is called mid-
turn (from inside the first tool's own real dispatch, simulating the
"user clicked Stop while a tool was running" case), and what's asserted is
the real tool call count and the real pushed event sequence, not internal
bookkeeping.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.models.chat import ChatSession


class _FakeToolUseStream:
    def __init__(self, tool_name: str, tool_input: dict, tool_id: str) -> None:
        self._tool_name = tool_name
        self._tool_input = tool_input
        self._tool_id = tool_id

    async def __aenter__(self) -> "_FakeToolUseStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> "_FakeToolUseStream":
        return self

    async def __anext__(self) -> None:
        raise StopAsyncIteration

    async def get_final_message(self) -> MagicMock:
        block = MagicMock()
        block.type = "tool_use"
        block.id = self._tool_id
        block.name = self._tool_name
        block.input = self._tool_input
        final = MagicMock()
        final.stop_reason = "tool_use"
        final.content = [block]
        final.usage = MagicMock(input_tokens=10, output_tokens=5)
        return final


class _FakeTextStream:
    def __init__(self, text: str) -> None:
        self._text = text

    async def __aenter__(self) -> "_FakeTextStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> "_FakeTextStream":
        return self

    async def __anext__(self) -> None:
        raise StopAsyncIteration

    async def get_final_message(self) -> MagicMock:
        block = MagicMock()
        block.type = "text"
        final = MagicMock()
        final.stop_reason = "end_turn"
        final.content = [block]
        final.usage = MagicMock(input_tokens=10, output_tokens=5)
        return final


async def _drain_until_done(session: ChatSession) -> list[dict]:
    events: list[dict] = []
    while True:
        ev = await asyncio.wait_for(session._queue.get(), timeout=5.0)
        events.append(ev)
        if ev.get("type") == "done":
            return events


@pytest.mark.asyncio
async def test_request_stop_skips_the_next_tool_call_and_finalizes(
    tmp_path: Path,
) -> None:
    session = ChatSession(session_id="td_stop_1", repo_path=str(tmp_path))
    agent = ChatAgent(session)
    call_count = {"n": 0}

    def fake_list_files_handler(root: object, repo: object, inp: object) -> str:
        call_count["n"] += 1
        # Simulates the user clicking Stop WHILE this first tool call is
        # already running — the real, honest scope: an in-flight call
        # still completes; only what comes AFTER is skipped.
        agent.request_stop()
        return "file1.txt\nfile2.txt"

    responses = [
        _FakeToolUseStream("list_files", {"path": "."}, tool_id="toolu_lf1"),
        # If the stop check didn't work, the graph would call the LLM
        # again and get this second tool_use — asserted below that it
        # never happens.
        _FakeToolUseStream("list_files", {"path": "."}, tool_id="toolu_lf2"),
        _FakeTextStream("should never be reached"),
    ]
    call_state = {"n": 0}

    def fake_stream(*args: object, **kwargs: object) -> object:
        resp = responses[call_state["n"]]
        call_state["n"] += 1
        return resp

    with (
        patch.object(
            ChatAgent,
            "_client",
            return_value=MagicMock(
                messages=MagicMock(stream=MagicMock(side_effect=fake_stream))
            ),
        ),
        patch(
            "app.agents.chat_agent.list_files_handler",
            side_effect=fake_list_files_handler,
        ),
        patch.object(agent, "_memory_read_context", new=AsyncMock(return_value="")),
        patch.object(agent, "_memory_write_outcome", new=AsyncMock()),
    ):
        events = []
        collector = asyncio.create_task(_drain_until_done(session))
        await agent.run("list files")
        events = await collector

    assert call_count["n"] == 1, "the second, post-stop tool call must never run"
    assert call_state["n"] == 1, (
        "the LLM must never be called a second time after a stop request "
        "(only the immediate no-op short-circuit call counts)"
    )
    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1
    assert done_events[0].get("stopped") is True


@pytest.mark.asyncio
async def test_normal_completion_has_no_stopped_flag(tmp_path: Path) -> None:
    """Zero-behavior-change proof: a turn that finishes on its own (no
    stop requested) must NOT carry a 'stopped' key at all — every existing
    caller/test that checks {"type": "done"} must keep seeing exactly
    that."""
    session = ChatSession(session_id="td_stop_2", repo_path=str(tmp_path))
    agent = ChatAgent(session)
    responses = [_FakeTextStream("all done, no tools needed")]
    call_state = {"n": 0}

    def fake_stream(*args: object, **kwargs: object) -> object:
        resp = responses[call_state["n"]]
        call_state["n"] += 1
        return resp

    with (
        patch.object(
            ChatAgent,
            "_client",
            return_value=MagicMock(
                messages=MagicMock(stream=MagicMock(side_effect=fake_stream))
            ),
        ),
        patch.object(agent, "_memory_read_context", new=AsyncMock(return_value="")),
        patch.object(agent, "_memory_write_outcome", new=AsyncMock()),
    ):
        collector = asyncio.create_task(_drain_until_done(session))
        await agent.run("hello")
        events = await collector

    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1
    assert "stopped" not in done_events[0]


@pytest.mark.asyncio
async def test_stop_flag_resets_between_turns(tmp_path: Path) -> None:
    """A stop requested during turn 1 (already finished) must not silently
    kill turn 2."""
    session = ChatSession(session_id="td_stop_3", repo_path=str(tmp_path))
    agent = ChatAgent(session)
    responses = [
        _FakeTextStream("turn one done"),
        _FakeTextStream("turn two done"),
    ]
    call_state = {"n": 0}

    def fake_stream(*args: object, **kwargs: object) -> object:
        resp = responses[call_state["n"]]
        call_state["n"] += 1
        return resp

    with (
        patch.object(
            ChatAgent,
            "_client",
            return_value=MagicMock(
                messages=MagicMock(stream=MagicMock(side_effect=fake_stream))
            ),
        ),
        patch.object(agent, "_memory_read_context", new=AsyncMock(return_value="")),
        patch.object(agent, "_memory_write_outcome", new=AsyncMock()),
    ):
        collector1 = asyncio.create_task(_drain_until_done(session))
        await agent.run("first message")
        events1 = await collector1
        agent.request_stop()  # requested AFTER turn 1 already finished

        collector2 = asyncio.create_task(_drain_until_done(session))
        await agent.run("second message")
        events2 = await collector2

    assert events1[-1].get("stopped") is not True
    # Turn 2 must run normally (its own real LLM call must have
    # happened) — not silently short-circuited by turn 1's leftover flag.
    assert call_state["n"] == 2
    assert events2[-1]["type"] == "done"
    assert events2[-1].get("stopped") is not True
