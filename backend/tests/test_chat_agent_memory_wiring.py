"""Tests for MASTER_AGENT_v2.md Phase 3.3 gap-closure — chat_agent.py had zero
memory read/write wiring (confirmed by grep before this change: no
embed_task_outcome/embed_failure/query_memory_context call anywhere in the
file). chat_agent.py's own LangGraph structural conversion stays deferred to
Phase 5 (per 3.3's own text) — this only applies the memory read/write
behavior, at ChatAgent.run()'s real natural unit of work: one call = one turn.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.models.chat import ChatSession

# ---------------------------------------------------------------------------
# _memory_read_context — isolated unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_read_context_returns_formatted_block_on_success() -> None:
    session = ChatSession(session_id="s1", repo_path="/tmp/repo")
    agent = ChatAgent(session)

    fake_mem = {
        "tasks": [
            {
                "task_id": "1",
                "outcome": "completed",
                "description": "d",
                "summary": "s",
                "files_changed": [],
                "similarity": 0.9,
            }
        ],
        "failures": [],
        "learnings": [],
        "procedures": [],
    }
    with (
        patch("app.db.session.new_isolated_async_engine") as mock_engine_factory,
        patch(
            "app.memory.store.query_memory_context",
            new=AsyncMock(return_value=fake_mem),
        ),
    ):
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_engine_factory.return_value = mock_engine
        block = await agent._memory_read_context("how does auth work")

    assert block != ""


@pytest.mark.asyncio
async def test_memory_read_context_returns_empty_string_on_failure() -> None:
    session = ChatSession(session_id="s2", repo_path="/tmp/repo")
    agent = ChatAgent(session)

    with patch(
        "app.db.session.new_isolated_async_engine", side_effect=RuntimeError("db down")
    ):
        block = await agent._memory_read_context("anything")

    assert block == ""


# ---------------------------------------------------------------------------
# _memory_write_outcome — isolated unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_write_outcome_completed_writes_task_outcome_only() -> None:
    session = ChatSession(session_id="s3", repo_path="/tmp/repo")
    agent = ChatAgent(session)

    with (
        patch("app.db.session.new_isolated_async_engine") as mock_engine_factory,
        patch("app.memory.store.embed_task_outcome", new=AsyncMock()) as mock_outcome,
        patch("app.memory.store.embed_failure", new=AsyncMock()) as mock_failure,
    ):
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_engine_factory.return_value = mock_engine
        await agent._memory_write_outcome("explain the auth flow", "It uses JWT.", None)

    mock_outcome.assert_awaited_once()
    kwargs = mock_outcome.await_args.kwargs
    assert kwargs["task_id"] == "s3"
    assert kwargs["outcome"] == "completed"
    assert kwargs["summary"] == "It uses JWT."
    mock_failure.assert_not_awaited()


@pytest.mark.asyncio
async def test_memory_write_outcome_with_error_writes_both() -> None:
    session = ChatSession(session_id="s4", repo_path="/tmp/repo")
    agent = ChatAgent(session)

    with (
        patch("app.db.session.new_isolated_async_engine") as mock_engine_factory,
        patch("app.memory.store.embed_task_outcome", new=AsyncMock()) as mock_outcome,
        patch("app.memory.store.embed_failure", new=AsyncMock()) as mock_failure,
    ):
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_engine_factory.return_value = mock_engine
        await agent._memory_write_outcome("do the thing", "", "API error: rate limited")

    assert mock_outcome.await_args.kwargs["outcome"] == "blocked"
    mock_failure.assert_awaited_once()
    assert (
        mock_failure.await_args.kwargs["error_description"] == "API error: rate limited"
    )


@pytest.mark.asyncio
async def test_memory_write_outcome_failure_does_not_raise() -> None:
    session = ChatSession(session_id="s5", repo_path="/tmp/repo")
    agent = ChatAgent(session)

    with patch(
        "app.db.session.new_isolated_async_engine", side_effect=RuntimeError("db down")
    ):
        await agent._memory_write_outcome("q", "a", None)
    # No exception propagated — test passing at all is the assertion.


# ---------------------------------------------------------------------------
# run() wiring — proves the two hooks are actually called from the real
# agentic loop, with the real user message / final answer / error, not just
# that the standalone methods work in isolation.
# ---------------------------------------------------------------------------


class _FakeStream:
    """Minimal fake for `async with client.messages.stream(...) as stream`.
    Yields zero delta events (the test doesn't need streaming text deltas),
    and get_final_message() returns a stop_reason="end_turn" text-only
    response — the model answers directly, no tool_use, one iteration."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> "_FakeStream":
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


@pytest.mark.asyncio
async def test_run_calls_memory_read_before_and_write_after() -> None:
    session = ChatSession(session_id="s6", repo_path="/tmp/repo")
    agent = ChatAgent(session)

    with (
        patch.object(
            agent, "_memory_read_context", new=AsyncMock(return_value="## past context")
        ) as mock_read,
        patch.object(agent, "_memory_write_outcome", new=AsyncMock()) as mock_write,
        patch.object(
            ChatAgent,
            "_client",
            return_value=MagicMock(
                messages=MagicMock(stream=MagicMock(return_value=_FakeStream("hi")))
            ),
        ),
    ):
        await agent.run("how does auth work here?")

    mock_read.assert_awaited_once_with("how does auth work here?")
    mock_write.assert_awaited_once()
    write_kwargs_or_args = mock_write.await_args
    assert write_kwargs_or_args is not None
    assert write_kwargs_or_args.args[0] == "how does auth work here?"
    assert write_kwargs_or_args.args[2] is None  # no error on a clean end_turn


def test_run_uses_memory_augmented_system_prompt_not_static_one() -> None:
    """Source-inspection guard: run() must build the per-call system_prompt
    (self._system + memory_block) and thread it into the graph's initial
    state, and _call_llm_node must pass THAT (not the static self._system
    directly) to the streaming call — otherwise the memory read would be
    computed and then silently discarded. Split across two methods since
    MASTER_AGENT_v2.md Phase 5.2 moved the streaming call into a real
    LangGraph node (_call_llm_node); run() itself only seeds initial state
    now."""
    run_source = inspect.getsource(ChatAgent.run)
    assert "system_prompt" in run_source
    assert '"system_prompt": system_prompt' in run_source
    assert "self._memory_read_context" in run_source

    node_source = inspect.getsource(ChatAgent._call_llm_node)
    assert "system=system_prompt" in node_source

    finalize_source = inspect.getsource(ChatAgent._finalize_node)
    assert "self._memory_write_outcome" in finalize_source
