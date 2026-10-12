"""C6 (owner decision, 2026-10-12): the chat answers questions about a
project and never changes anything; "Make this a task" turns a conversation
into a task. Attachments and project notes are gone.

No AI runs: the model client is a fake that records what it was offered.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from app.agents.chat_agent import CHAT_AGENT_TOOL_NAMES, ChatAgent
from app.main import app

WRITERS = [
    "edit_file",
    "write_file",
    "delete_file",
    "bash",
    "git_commit",
    "git_push",
    "git_branch",
    "run_tests",
    "run_migration",
    "seed_database",
    "docker_exec",
    "npm_install",
    "fetch_url",
    "browser_open",
    "memory_write",
    "repeat_previous_task",
    "list_env_vars",
    "read_logs",
    "export_markdown",
]


# -- the chat only reads ------------------------------------------------------


def test_the_chat_is_offered_read_tools_only() -> None:
    from app.fleet.tool_manifest import TOOL_MANIFEST

    assert {"read_file", "search_code", "get_file_tree", "git_log"} <= (
        CHAT_AGENT_TOOL_NAMES
    )
    for name in WRITERS:
        assert name not in CHAT_AGENT_TOOL_NAMES, name
    for name in CHAT_AGENT_TOOL_NAMES - {"submit_result", "ask_human_to_choose"}:
        entry = TOOL_MANIFEST[name]
        assert set(entry.permissions) <= {"read_repo", "read_memory"}, name


class _Stop(Exception):
    pass


def test_the_model_call_offers_only_those_tools(tmp_path: Any) -> None:
    from app.models.chat import ChatSession

    offered: list[set[str]] = []

    def stream(**kw: Any) -> Any:
        offered.append({t["name"] for t in kw["tools"]})
        raise _Stop

    agent = ChatAgent(ChatSession(session_id="c6-offer", repo_path=str(tmp_path)))
    agent.session.history.append({"role": "user", "content": "where is login?"})
    fake = MagicMock()
    fake.messages.stream = stream
    with patch.object(ChatAgent, "_client", return_value=fake):
        try:
            asyncio.run(agent._call_llm_node({"iteration": 0}))  # type: ignore[typeddict-item]
        except _Stop:
            pass
    assert offered and offered[0] == set(CHAT_AGENT_TOOL_NAMES)


@pytest.mark.parametrize("name", ["edit_file", "bash", "run_migration", "git_push"])
def test_a_write_tool_is_refused_even_if_the_model_asks(name: str) -> None:
    agent = ChatAgent.__new__(ChatAgent)
    agent.session = MagicMock()
    agent.session.session_id = "c6-refuse"
    agent.session.push = AsyncMock()
    agent.session.history = []
    agent._current_tool_use_id = ""
    agent._current_trace_id = ""
    agent._stop_requested = False
    with patch.object(agent, "_execute_tool", new=AsyncMock()) as run:
        asyncio.run(
            agent._execute_tool_node(
                {
                    "pending_tool_uses": [
                        {"id": "t1", "name": name, "input": {"path": "a.py"}}
                    ],
                    "verification": {"read": True},
                }  # type: ignore[typeddict-item]
            )
        )
    run.assert_not_called()
    outputs = [
        c.args[0].get("output", "")
        for c in agent.session.push.call_args_list
        if c.args[0].get("type") == "tool_result"
    ]
    assert outputs and "only reads and answers" in outputs[0]


def test_attachments_and_project_notes_are_gone() -> None:
    from app.api import chat

    assert not hasattr(chat, "_prepare_attachments")
    assert "attachments" not in chat.SendMessageRequest.model_fields
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any(p.endswith("/notes") for p in paths if p.startswith("/api/projects"))


# -- Make this a task ------------------------------------------------------------


def _db(fn):  # type: ignore[no-untyped-def]
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings

    async def _run():  # type: ignore[no-untyped-def]
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                return await fn(s)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


@pytest.fixture
def chat(tmp_path: Any) -> Any:
    from app.db.models import ChatSessionRecord, DevTask, Project

    async def make(s):  # type: ignore[no-untyped-def]
        p = Project(
            name="C6 project", local_path=str(tmp_path), source="local_existing"
        )
        s.add(p)
        await s.commit()
        await s.refresh(p)
        for sid, owner, pid in (
            ("c6-chat", "admin", p.id),
            ("c6-other", "someone-else", p.id),
            ("c6-loose", "admin", None),
        ):
            s.add(
                ChatSessionRecord(
                    id=sid,
                    repo_path=str(tmp_path) if pid else "/tmp/c6-nowhere",
                    created_by=owner,
                    project_id=pid,
                )
            )
        await s.commit()
        for role, content in (
            ("user", "Why does login fail with a 500?"),
            ("assistant", "auth.py line 40 reads a missing JWT_SECRET setting."),
            ("user", "Add a clear error when JWT_SECRET is missing"),
        ):
            await s.execute(
                text(
                    "INSERT INTO chat_messages (session_id, repo_path, role, content) "
                    "VALUES ('c6-chat', :r, :role, :c)"
                ),
                {"r": str(tmp_path), "role": role, "c": content},
            )
        await s.commit()
        return p.id

    pid = _db(make)
    yield pid

    async def clean(s):  # type: ignore[no-untyped-def]
        await s.execute(text("DELETE FROM chat_messages WHERE session_id LIKE 'c6-%'"))
        await s.execute(
            delete(ChatSessionRecord).where(ChatSessionRecord.id.like("c6-%"))
        )
        await s.execute(delete(DevTask).where(DevTask.project_id == pid))
        await s.execute(delete(Project).where(Project.id == pid))
        await s.commit()

    _db(clean)


def _as(user: str) -> Any:
    from app.middleware import rbac

    app.dependency_overrides[rbac.require_approver] = lambda: user
    app.dependency_overrides[rbac.require_authenticated] = lambda: user


def test_make_this_a_task_creates_one_task_in_the_chats_project(chat: int) -> None:
    from app.db.models import DevTask

    _as("admin")
    try:
        with TestClient(app) as client:
            headers = {"Idempotency-Key": f"c6-{uuid.uuid4()}"}
            r = client.post(
                "/api/chat/sessions/c6-chat/make-task", json={}, headers=headers
            )
            again = client.post(
                "/api/chat/sessions/c6-chat/make-task", json={}, headers=headers
            )
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 201, r.text
    assert again.json()["taskId"] == r.json()["taskId"]  # a retry makes no second task

    async def tasks(s):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        return list(
            (
                await s.execute(select(DevTask).where(DevTask.project_id == chat))
            ).scalars()
        )

    [task] = _db(tasks)
    assert task.title == "Add a clear error when JWT_SECRET is missing"
    assert "auth.py line 40" in task.description  # the conversation goes with it
    assert task.created_by == "admin"


def test_another_users_chat_and_a_chat_without_project(chat: int) -> None:
    _as("admin")
    try:
        with TestClient(app) as client:
            other = client.post("/api/chat/sessions/c6-other/make-task", json={})
            loose = client.post(
                "/api/chat/sessions/c6-loose/make-task", json={"request": "do it"}
            )
    finally:
        app.dependency_overrides.clear()
    assert other.status_code == 404  # Sol A07: not your chat
    assert loose.status_code == 400 and "not linked to a project" in loose.text
