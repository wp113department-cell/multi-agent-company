"""Tests for MASTER_AGENT_v2.md Phase 5.2 — chat_agent.py's real
interrupt()-based LangGraph conversion.

The core claim under test: a confirmation-gated tool's real side effect
(here, a git push) executes EXACTLY ONCE across a pause/resume cycle — the
specific bug the first (superseded) whole-loop-as-one-node design would
have had. This is proven directly against the real compiled graph
(app.agents.chat_agent.ChatAgent._graph), not by asserting on internal
bookkeeping — a fake Anthropic streaming client drives two real LLM turns
(tool_use -> confirmation pause -> resume -> end_turn), and the actual
git-call counter is what's asserted on.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.models.chat import ChatSession


class _FakeToolUseStream:
    """Minimal fake for `async with client.messages.stream(...) as stream`
    that ends the turn with a single tool_use block — the model decided to
    call one tool."""

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
    """Minimal fake for a plain end_turn text response — no tool calls."""

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


def _patched_agent(agent: ChatAgent, responses: list, git_call_count: dict):
    """Context manager stack: fake streaming client returning `responses`
    in order (one per call to messages.stream), fake _git counting real
    calls, memory read/write no-ops (out of scope for this test)."""
    call_state = {"n": 0}

    def fake_stream(*args: object, **kwargs: object):
        resp = responses[call_state["n"]]
        call_state["n"] += 1
        return resp

    def fake_git(args: list, cwd: str, timeout: int = 30) -> str:
        git_call_count["n"] += 1
        return "pushed ok"

    return (
        patch.object(
            ChatAgent,
            "_client",
            return_value=MagicMock(
                messages=MagicMock(stream=MagicMock(side_effect=fake_stream))
            ),
        ),
        patch("app.agents.chat_agent._git", side_effect=fake_git),
        patch.object(agent, "_memory_read_context", new=AsyncMock(return_value="")),
        patch.object(agent, "_memory_write_outcome", new=AsyncMock()),
    )


# test_confirmed_git_push_runs_exactly_once_across_pause_and_resume: removed (C6, 2026-10-12) — the chat only reads and answers; it no longer pushes, opens PRs or changes files, so there is nothing to confirm. See tests/test_c6_chat_questions_only.py

# test_denied_git_push_never_runs: removed (C6, 2026-10-12) — the chat only reads and answers; it no longer pushes, opens PRs or changes files, so there is nothing to confirm. See tests/test_c6_chat_questions_only.py


def _patched_agent_for_create_pr(
    agent: ChatAgent, responses: list, gh_call_count: dict
):
    """Same shape as _patched_agent, but for create_pr: patches
    _run_subprocess (the real chokepoint for `gh pr create`) instead of
    _git, since that's the call whose count proves whether the PR was
    actually created."""
    call_state = {"n": 0}

    def fake_stream(*args: object, **kwargs: object):
        resp = responses[call_state["n"]]
        call_state["n"] += 1
        return resp

    def fake_run_subprocess(
        command: str,
        cwd: str,
        timeout: int = 120,
        *,
        fail_on_nonzero_exit: bool = False,
    ) -> str:
        gh_call_count["n"] += 1
        return "https://github.com/example/repo/pull/1"

    return (
        patch.object(
            ChatAgent,
            "_client",
            return_value=MagicMock(
                messages=MagicMock(stream=MagicMock(side_effect=fake_stream))
            ),
        ),
        patch("app.agents.chat_agent._run_subprocess", side_effect=fake_run_subprocess),
        patch.object(agent, "_memory_read_context", new=AsyncMock(return_value="")),
        patch.object(agent, "_memory_write_outcome", new=AsyncMock()),
    )


# test_confirmed_create_pr_runs_exactly_once_across_pause_and_resume: removed (C6, 2026-10-12) — the chat only reads and answers; it no longer pushes, opens PRs or changes files, so there is nothing to confirm. See tests/test_c6_chat_questions_only.py

# test_denied_create_pr_never_runs: removed (C6, 2026-10-12) — the chat only reads and answers; it no longer pushes, opens PRs or changes files, so there is nothing to confirm. See tests/test_c6_chat_questions_only.py


@pytest.mark.asyncio
async def test_resume_with_mismatched_action_id_is_a_safe_no_op() -> None:
    session = ChatSession(session_id="td_graph_push_mismatch", repo_path="/tmp/repo")
    agent = ChatAgent(session)
    git_call_count = {"n": 0}
    responses = [
        _FakeToolUseStream("git_push", {"branch": "main"}, tool_id="toolu_push3"),
        _FakeTextStream("Pushed."),
    ]
    p1, p2, p3, p4 = _patched_agent(agent, responses, git_call_count)

    with p1, p2, p3, p4:
        await agent.run("push")
        resumed = await agent.resume("totally-wrong-action-id", True)
        assert resumed is False

    assert git_call_count["n"] == 0


@pytest.mark.asyncio
async def test_turn_with_no_confirmation_needed_completes_in_one_run_call() -> None:
    """A turn that never touches a confirmation-gated tool must complete
    entirely within run() — no pause, no resume() needed — proving the
    graph conversion didn't change behavior for the common case."""
    session = ChatSession(session_id="td_graph_no_confirm", repo_path="/tmp/repo")
    agent = ChatAgent(session)
    responses = [_FakeTextStream("The answer is 4.")]

    def fake_stream(*args: object, **kwargs: object):
        return responses[0]

    with (
        patch.object(
            ChatAgent,
            "_client",
            return_value=MagicMock(
                messages=MagicMock(stream=MagicMock(side_effect=fake_stream))
            ),
        ),
        patch.object(agent, "_memory_read_context", new=AsyncMock(return_value="")),
        patch.object(agent, "_memory_write_outcome", new=AsyncMock()) as mock_write,
    ):
        await agent.run("what is 2+2?")

    mock_write.assert_awaited_once()
    events = []
    while not session._queue.empty():
        events.append(session._queue.get_nowait())
    assert events[-1]["type"] == "done"


def test_confirm_uses_the_stable_anthropic_tool_use_id_not_a_fresh_uuid() -> None:
    """Source-inspection guard for the specific bug this design fixes: a
    freshly generated uuid4() per replay pass would silently orphan the
    pending_approvals row and mismatch the id the client already has."""
    import inspect

    source = inspect.getsource(ChatAgent._confirm)
    assert "self._current_tool_use_id" in source

    node_source = inspect.getsource(ChatAgent._execute_tool_node)
    assert "self._current_tool_use_id = tu" in node_source


# ---------------------------------------------------------------------------
# HITL audit-trail wiring (Phase 5.5 integration) — real DB, same convention
# as test_approval_gate.py. Chat confirmations must be as visible to the
# fleet's generic pending_approvals/audit_log as plan_review/git_push are.
# ---------------------------------------------------------------------------


async def _cleanup_pending_approval(thread_id: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import PendingApproval

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(
                delete(PendingApproval).where(PendingApproval.thread_id == thread_id)
            )
            await session.commit()
    finally:
        await engine.dispose()


# test_confirmation_writes_a_real_pending_approval_row_and_decides_it: removed (C6, 2026-10-12) — the chat only reads and answers; it no longer pushes, opens PRs or changes files, so there is nothing to confirm. See tests/test_c6_chat_questions_only.py

# test_approval_gate_failure_never_blocks_the_real_pause_resume_flow: removed (C6, 2026-10-12) — the chat only reads and answers; it no longer pushes, opens PRs or changes files, so there is nothing to confirm. See tests/test_c6_chat_questions_only.py
