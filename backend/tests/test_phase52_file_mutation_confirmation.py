"""Gap-closure Day 5 (root cause 2, answers.md Q39) — real proof that
chat_agent.py's `delete_file` and `write_file`-on-an-existing-file now pause
for confirmation via the same real interrupt()-based graph
`test_phase52_chat_graph_interrupt.py` already proved for `git_push`, and
that the actual side effect (a real file write/delete on disk, not a mock)
executes exactly once across a pause/resume cycle — never before
confirmation, never twice on resume.

Reuses `test_phase52_chat_graph_interrupt.py`'s exact fake-streaming-client
pattern; the only difference is the side effect under test is a real
filesystem write instead of a `_git` call, so a real `tmp_path` repo root is
used instead of the git tests' unused `/tmp/repo` placeholder.
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


async def _resume_action(
    agent: ChatAgent, session: ChatSession, approved: bool
) -> bool:
    config = {"configurable": {"thread_id": session.session_id}}
    snapshot = await agent._graph.aget_state(config)
    action_id = next(
        i.value["action_id"] for task in snapshot.tasks for i in task.interrupts
    )
    return await agent.resume(action_id, approved)


@pytest.mark.asyncio
async def test_confirmed_delete_file_runs_exactly_once_across_pause_and_resume(
    tmp_path: Path,
) -> None:
    target = tmp_path / "doomed.txt"
    target.write_text("real content that would be really deleted")

    session = ChatSession(session_id="td_delete_approve", repo_path=str(tmp_path))
    agent = ChatAgent(session)
    responses = [
        _FakeToolUseStream("delete_file", {"path": "doomed.txt"}, tool_id="toolu_del1"),
        _FakeTextStream("Deleted."),
    ]
    p1, p2, p3 = _patched_agent(agent, responses)

    with p1, p2, p3:
        await agent.run("delete doomed.txt")

        # Paused at the confirmation — the real file must still exist.
        assert target.exists()

        resumed = await _resume_action(agent, session, True)
        assert resumed is True

    assert not target.exists()


@pytest.mark.asyncio
async def test_denied_delete_file_never_runs(tmp_path: Path) -> None:
    target = tmp_path / "survivor.txt"
    target.write_text("real content that must survive")

    session = ChatSession(session_id="td_delete_deny", repo_path=str(tmp_path))
    agent = ChatAgent(session)
    responses = [
        _FakeToolUseStream(
            "delete_file", {"path": "survivor.txt"}, tool_id="toolu_del2"
        ),
        _FakeTextStream("Understood, not deleting."),
    ]
    p1, p2, p3 = _patched_agent(agent, responses)

    with p1, p2, p3:
        await agent.run("delete survivor.txt")
        resumed = await _resume_action(agent, session, False)
        assert resumed is True

    assert target.exists()
    assert target.read_text() == "real content that must survive"


@pytest.mark.asyncio
async def test_confirmed_write_file_overwrite_runs_exactly_once(tmp_path: Path) -> None:
    """write_file on a file that ALREADY EXISTS is the gated case — real
    content must not change until approved, and must change exactly once
    on resume, not the old content re-appearing or a double-write."""
    target = tmp_path / "existing.py"
    target.write_text("old content")

    session = ChatSession(
        session_id="td_write_overwrite_approve", repo_path=str(tmp_path)
    )
    agent = ChatAgent(session)
    responses = [
        # Gap-closure Day 16 (Stage 1.2, answers.md): write_file is now
        # blocking_until-gated on a prior read this session (previously
        # dead config on _VERIFICATION_CFG, now enforced) — a real,
        # separate concern from this test's own confirmation-gate subject.
        _FakeToolUseStream(
            "read_file", {"path": "existing.py"}, tool_id="toolu_read_pre1"
        ),
        _FakeToolUseStream(
            "write_file",
            {"path": "existing.py", "content": "new content"},
            tool_id="toolu_write1",
        ),
        _FakeTextStream("Written."),
    ]
    p1, p2, p3 = _patched_agent(agent, responses)

    with p1, p2, p3:
        await agent.run("overwrite existing.py")

        # Paused — old content must be untouched.
        assert target.read_text() == "old content"

        resumed = await _resume_action(agent, session, True)
        assert resumed is True

    assert target.read_text() == "new content"


@pytest.mark.asyncio
async def test_denied_write_file_overwrite_leaves_old_content_untouched(
    tmp_path: Path,
) -> None:
    target = tmp_path / "protected_by_choice.py"
    target.write_text("original content must survive")

    session = ChatSession(session_id="td_write_overwrite_deny", repo_path=str(tmp_path))
    agent = ChatAgent(session)
    responses = [
        # Gap-closure Day 16: write_file is now blocking_until-gated on a
        # prior read this session — see the comment on the previous test.
        _FakeToolUseStream(
            "read_file",
            {"path": "protected_by_choice.py"},
            tool_id="toolu_read_pre2",
        ),
        _FakeToolUseStream(
            "write_file",
            {"path": "protected_by_choice.py", "content": "attempted overwrite"},
            tool_id="toolu_write2",
        ),
        _FakeTextStream("Understood, leaving it alone."),
    ]
    p1, p2, p3 = _patched_agent(agent, responses)

    with p1, p2, p3:
        await agent.run("overwrite protected_by_choice.py")
        resumed = await _resume_action(agent, session, False)
        assert resumed is True

    assert target.read_text() == "original content must survive"


@pytest.mark.asyncio
async def test_write_file_creating_a_new_file_needs_no_confirmation(
    tmp_path: Path,
) -> None:
    """Creating a brand-new file (nothing exists yet to lose) must complete
    in a single run() call, same as the pre-existing 'no confirmation
    needed' turn shape — proves normal coding work isn't disrupted."""
    target = tmp_path / "brand_new_file.py"
    assert not target.exists()
    # Gap-closure Day 16: write_file is now blocking_until-gated on a prior
    # read this session — a real, existing file to read first (the target
    # itself doesn't exist yet, so it can't be what's read).
    (tmp_path / "existing_sibling.py").write_text("# an existing file\n")

    session = ChatSession(session_id="td_write_new_no_confirm", repo_path=str(tmp_path))
    agent = ChatAgent(session)
    responses = [
        _FakeToolUseStream(
            "read_file", {"path": "existing_sibling.py"}, tool_id="toolu_read_pre3"
        ),
        _FakeToolUseStream(
            "write_file",
            {"path": "brand_new_file.py", "content": "print('hello')"},
            tool_id="toolu_write3",
        ),
        _FakeTextStream("Created."),
    ]
    p1, p2, p3 = _patched_agent(agent, responses)

    with p1, p2, p3:
        await agent.run("create brand_new_file.py")

    assert target.exists()
    assert target.read_text() == "print('hello')"
