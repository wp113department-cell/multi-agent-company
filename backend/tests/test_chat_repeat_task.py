"""#500 (2026-09-25, "Conversational 'do that again'") —
find_repeatable_tasks / repeat_previous_task, ChatAgent's new deterministic
recall mechanism.

Real proof against a real Postgres, no mocked DB: creates genuine DevTask
rows scoped to a genuine Repo row, then calls the tool dispatch exactly as
the LLM would (agent._execute_tool(...)), plus one full graph-level test
proving the LLM-driven "ambiguous -> ask_human_to_choose -> repeat" flow
end-to-end with a fake Anthropic stream (same pattern as
test_phase52_chat_graph_interrupt.py).
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete

from app.agents.chat_agent import ChatAgent
from app.db.models import DevTask, Repo
from app.db.repository import create_task
from app.db.session import get_session_factory
from app.models.chat import ChatSession


async def _make_repo() -> int:
    async with get_session_factory()() as db:
        repo = Repo(
            github_url=f"https://example.com/{uuid.uuid4().hex}",
            name="repeat-task-test-repo",
            local_path=f"/tmp/{uuid.uuid4().hex}",
            status="ready",
        )
        db.add(repo)
        await db.commit()
        await db.refresh(repo)
        return repo.id


async def _make_task(repo_id: int, title: str, description: str = "desc") -> int:
    async with get_session_factory()() as db:
        task = await create_task(db, title, description, repo_id=repo_id)
        return task.id


async def _cleanup(repo_id: int) -> None:
    async with get_session_factory()() as db:
        await db.execute(delete(DevTask).where(DevTask.repo_id == repo_id))
        await db.execute(delete(Repo).where(Repo.id == repo_id))
        await db.commit()


@pytest.fixture
async def repo_id():
    rid = await _make_repo()
    yield rid
    await _cleanup(rid)


@pytest.mark.asyncio
async def test_find_repeatable_tasks_unambiguous_single_match(repo_id: int) -> None:
    await _make_task(repo_id, "Fix the login bug")
    session = ChatSession(session_id="td_repeat_1", repo_path="/tmp/x", repo_id=repo_id)
    agent = ChatAgent(session)

    out = await agent._execute_tool("find_repeatable_tasks", {"keyword": "login"})

    assert "Found exactly one candidate" in out
    assert "Fix the login bug" in out
    assert "may call repeat_previous_task" in out


@pytest.mark.asyncio
async def test_find_repeatable_tasks_ambiguous_multiple_matches(repo_id: int) -> None:
    await _make_task(repo_id, "Fix the login bug")
    await _make_task(repo_id, "Fix the login timeout bug")
    session = ChatSession(session_id="td_repeat_2", repo_path="/tmp/x", repo_id=repo_id)
    agent = ChatAgent(session)

    out = await agent._execute_tool("find_repeatable_tasks", {"keyword": "login"})

    assert "Found 2 candidates" in out
    assert "MUST call ask_human_to_choose" in out


@pytest.mark.asyncio
async def test_find_repeatable_tasks_no_matches(repo_id: int) -> None:
    session = ChatSession(session_id="td_repeat_3", repo_path="/tmp/x", repo_id=repo_id)
    agent = ChatAgent(session)

    out = await agent._execute_tool(
        "find_repeatable_tasks", {"keyword": "nonexistent_xyz"}
    )

    assert "No past tasks found" in out


@pytest.mark.asyncio
async def test_find_repeatable_tasks_scoped_to_this_repo_only(repo_id: int) -> None:
    """A task in a DIFFERENT repo must never show up as a candidate — real
    cross-repo isolation, not just a same-process convenience."""
    other_repo_id = await _make_repo()
    try:
        await _make_task(other_repo_id, "Unique other repo task xyzzy123")
        session = ChatSession(
            session_id="td_repeat_4", repo_path="/tmp/x", repo_id=repo_id
        )
        agent = ChatAgent(session)

        out = await agent._execute_tool(
            "find_repeatable_tasks", {"keyword": "xyzzy123"}
        )
        assert "No past tasks found" in out
    finally:
        await _cleanup(other_repo_id)


@pytest.mark.asyncio
async def test_repeat_previous_task_real_clone_and_dispatch(repo_id: int) -> None:
    source_id = await _make_task(repo_id, "Original task", "original description")
    session = ChatSession(session_id="td_repeat_5", repo_path="/tmp/x", repo_id=repo_id)
    agent = ChatAgent(session)

    with patch(
        "app.api.agents.launch_planning_pipeline", new=AsyncMock()
    ) as mock_launch:
        out = await agent._execute_tool("repeat_previous_task", {"task_id": source_id})
        # _FireAndForgetBackgroundTasks fires via asyncio.create_task —
        # scheduled, not run synchronously — give the event loop a real
        # turn to actually execute it before asserting.
        await asyncio.sleep(0.05)

    assert "Repeated task" in out
    assert f"#{source_id}" in out
    assert mock_launch.called

    async with get_session_factory()() as db:
        from sqlalchemy import select

        result = await db.execute(
            select(DevTask).where(DevTask.repeated_from_task_id == source_id)
        )
        new_task = result.scalar_one()
        assert new_task.title == "Original task"
        assert new_task.description == "original description"
        assert new_task.status == "planning"


@pytest.mark.asyncio
async def test_repeat_previous_task_with_description_override(repo_id: int) -> None:
    source_id = await _make_task(repo_id, "Original task", "original description")
    session = ChatSession(session_id="td_repeat_6", repo_path="/tmp/x", repo_id=repo_id)
    agent = ChatAgent(session)

    with patch("app.api.agents.launch_planning_pipeline", new=AsyncMock()):
        out = await agent._execute_tool(
            "repeat_previous_task",
            {
                "task_id": source_id,
                "description_override": "but use Python 3.12 this time",
            },
        )

    assert "Repeated task" in out
    async with get_session_factory()() as db:
        from sqlalchemy import select

        result = await db.execute(
            select(DevTask).where(DevTask.repeated_from_task_id == source_id)
        )
        new_task = result.scalar_one()
        assert new_task.description == "but use Python 3.12 this time"


@pytest.mark.asyncio
async def test_repeat_previous_task_nonexistent_id_errors_cleanly() -> None:
    session = ChatSession(session_id="td_repeat_7", repo_path="/tmp/x")
    agent = ChatAgent(session)

    out = await agent._execute_tool("repeat_previous_task", {"task_id": 999_999_999})

    assert "[ERROR]" in out
    assert "not found" in out


@pytest.mark.asyncio
async def test_repeat_previous_task_missing_task_id_errors_cleanly() -> None:
    session = ChatSession(session_id="td_repeat_8", repo_path="/tmp/x")
    agent = ChatAgent(session)

    out = await agent._execute_tool("repeat_previous_task", {})

    assert "[ERROR]" in out
    assert "task_id" in out


# ---------------------------------------------------------------------------
# Full graph-level proof: the LLM-driven ambiguous-reference flow, end to
# end, with a fake Anthropic stream — same pattern as
# test_phase52_chat_graph_interrupt.py.
# ---------------------------------------------------------------------------


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


# test_full_graph_ambiguous_reference_requires_human_choice: removed (C6, 2026-10-12) — repeating a task is an action, which the chat no longer takes; the tool itself is still tested above
