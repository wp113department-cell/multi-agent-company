"""Gap-closure Day 16 (Stage 1.2, answers.md) — proves chat_agent.py's
_VERIFICATION_CFG is now genuinely enforced, not dead config. Before this,
ChatGraphState had no `verification` key at all and _execute_tool_node never
read or wrote _VERIFICATION_CFG in any way — AGENT_CONTRACT's own
"expected_verification": {"read": "read_file or search_code must run before
write/bash tools"} was pure documentation nobody enforced.

Drives the real compiled graph (ChatAgent._graph) through real LLM turns via
a fake Anthropic streaming client — the same established pattern
test_phase52_chat_graph_interrupt.py already uses — not internal bookkeeping
assertions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.models.chat import ChatSession


class _FakeToolUseStream:
    def __init__(
        self, tool_name: str, tool_input: dict[str, Any], tool_id: str
    ) -> None:
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


def _last_tool_result(agent: ChatAgent) -> str:
    """_call_llm_node appends its own 'assistant' entry to session.history
    after every turn (including the final end_turn text) — so the LAST
    history entry is never the tool result itself, it's whatever the model
    said afterward. Search backward for the most recent real tool_result
    entry instead of assuming a fixed index."""
    for entry in reversed(agent.session.history):
        if entry.get("role") == "user":
            content = entry.get("content")
            if (
                isinstance(content, list)
                and content
                and content[0].get("type") == "tool_result"
            ):
                result: str = content[0]["content"]
                return result
    raise AssertionError("no tool_result entry found in session.history")


def _patched_agent(agent: ChatAgent, responses: list[Any]) -> tuple[Any, Any, Any]:
    call_state = {"n": 0}

    def fake_stream(*args: object, **kwargs: object) -> Any:
        resp = responses[call_state["n"]]
        call_state["n"] += 1
        return resp

    return (
        patch.object(
            ChatAgent,
            "_client",
            return_value=MagicMock(
                messages=MagicMock(stream=MagicMock(side_effect=fake_stream))
            ),
        ),
        patch.object(agent, "_memory_read_context", new=AsyncMock(return_value="")),
        patch.object(agent, "_memory_write_outcome", new=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_bash_is_refused_before_any_read_this_session(tmp_path: Path) -> None:
    session = ChatSession(session_id="td_gap16_bash_blocked", repo_path=str(tmp_path))
    agent = ChatAgent(session)
    responses = [
        _FakeToolUseStream(
            "bash", {"command": "echo should-not-run"}, tool_id="toolu_bash1"
        ),
        _FakeTextStream("Understood."),
    ]
    p1, p2, p3 = _patched_agent(agent, responses)

    with p1, p2, p3:
        await agent.run("run echo for me")

    tool_result = _last_tool_result(agent)
    assert tool_result.startswith("[POLICY DENIED]")
    assert "read" in tool_result


@pytest.mark.asyncio
async def test_bash_succeeds_after_a_real_read_this_session(tmp_path: Path) -> None:
    (tmp_path / "real_file.txt").write_text("hello from a real file\n")
    session = ChatSession(session_id="td_gap16_bash_allowed", repo_path=str(tmp_path))
    agent = ChatAgent(session)
    responses = [
        _FakeToolUseStream(
            "read_file", {"path": "real_file.txt"}, tool_id="toolu_read1"
        ),
        _FakeToolUseStream(
            "bash", {"command": "echo now-allowed"}, tool_id="toolu_bash2"
        ),
        _FakeTextStream("Done."),
    ]
    p1, p2, p3 = _patched_agent(agent, responses)

    with p1, p2, p3:
        await agent.run("read the file then run echo")

    tool_result = _last_tool_result(agent)
    assert not tool_result.startswith("[POLICY DENIED]")
    assert "now-allowed" in tool_result


@pytest.mark.asyncio
async def test_verification_read_flag_persists_across_separate_run_calls(
    tmp_path: Path,
) -> None:
    """The real behavior this was built for: a file read in an earlier turn
    must still count in a LATER, separate agent.run() call — not reset
    every user message. Two independent agent.run() calls on the same
    session, matching how the real API actually drives multi-turn chat."""
    (tmp_path / "real_file.txt").write_text("hello\n")
    session = ChatSession(session_id="td_gap16_persists", repo_path=str(tmp_path))
    agent = ChatAgent(session)

    turn1_responses = [
        _FakeToolUseStream(
            "read_file", {"path": "real_file.txt"}, tool_id="toolu_read2"
        ),
        _FakeTextStream("Read it."),
    ]
    p1, p2, p3 = _patched_agent(agent, turn1_responses)
    with p1, p2, p3:
        await agent.run("read the file")

    turn2_responses = [
        _FakeToolUseStream(
            "bash", {"command": "echo still-allowed"}, tool_id="toolu_bash3"
        ),
        _FakeTextStream("Done."),
    ]
    p1, p2, p3 = _patched_agent(agent, turn2_responses)
    with p1, p2, p3:
        await agent.run("now run echo")

    tool_result = _last_tool_result(agent)
    assert not tool_result.startswith("[POLICY DENIED]")
    assert "still-allowed" in tool_result


@pytest.mark.asyncio
async def test_write_file_new_file_creation_still_blocked_before_any_read(
    tmp_path: Path,
) -> None:
    """blocking_until applies to write_file unconditionally (any prior read
    in the session satisfies it) — this is a SEPARATE, orthogonal concern
    from gap-closure Day 5's "new file creation skips human confirmation"
    design; that gate is about approval, this one is about due-diligence
    verification, and neither overrides the other."""
    session = ChatSession(session_id="td_gap16_write_blocked", repo_path=str(tmp_path))
    agent = ChatAgent(session)
    responses = [
        _FakeToolUseStream(
            "write_file",
            {"path": "new_file.txt", "content": "hello"},
            tool_id="toolu_write1",
        ),
        _FakeTextStream("Understood."),
    ]
    p1, p2, p3 = _patched_agent(agent, responses)

    with p1, p2, p3:
        await agent.run("create a new file")

    tool_result = _last_tool_result(agent)
    assert tool_result.startswith("[POLICY DENIED]")
    assert not (
        tmp_path / "new_file.txt"
    ).exists(), "the write must never have actually executed"
