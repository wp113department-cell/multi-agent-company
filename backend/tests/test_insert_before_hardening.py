"""insert_before tool #48 — tool_enhance.md productionization pass
(2026-08-20).

Real finding: identical shape to tool #46's insert_after (its exact
mirror-image sibling) — same "advertised but never dispatched" bug
class as tools #4/#6/#22/#25/#33/#44/#45/#46. insert_before was already
in CHAT_TOOLS but chat_agent.py had zero dispatch branch, so every real
interactive call would have hit "[ERROR] Unknown tool". Its
worktree-boundary handling was already correct (tool #11's fix,
re-verified here, not re-fixed).

Every test here uses a real file on disk and proves the fix against
the REAL dispatch methods (ChatAgent._execute_tool and the real
make_chat_handlers() handler).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.insert_before import INSERT_BEFORE_TOOL


def _real_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "f.py").write_text("def foo():\n    pass\n\ndef bar():\n    pass\n")
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_insert_before_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_insert_before_tool_schema_requires_fields() -> None:
    assert INSERT_BEFORE_TOOL["name"] == "insert_before"
    assert INSERT_BEFORE_TOOL["input_schema"]["required"] == [  # type: ignore[index]
        "path",
        "pattern",
        "content",
    ]


def test_insert_before_is_in_chat_tools_exactly_once() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("insert_before") == 1


# ---------------------------------------------------------------------------
# The previously-unreachable tool — now reachable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_insert_before_real_insert(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "insert_before",
        {"path": "f.py", "pattern": "def bar", "content": "# comment before bar"},
    )
    assert result.startswith("Inserted")

    content = (repo / "f.py").read_text()
    assert "# comment before bar\ndef bar():\n    pass\n" in content


@pytest.mark.asyncio
async def test_chat_agent_insert_before_pattern_not_found(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "insert_before",
        {"path": "f.py", "pattern": "nonexistent_xyz", "content": "z"},
    )
    assert result.startswith("[WARN]")


@pytest.mark.asyncio
async def test_chat_agent_insert_before_rejects_protected_path(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "insert_before", {"path": ".env", "pattern": "x", "content": "y"}
    )
    assert result.startswith("[BLOCKED]")


@pytest.mark.asyncio
async def test_chat_agent_insert_before_rejects_outside_repo_path(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo)

    result = await agent._execute_tool(
        "insert_before",
        {"path": "/etc/hostname", "pattern": "x", "content": "y"},
    )
    assert result.startswith("[BLOCKED]")


# ---------------------------------------------------------------------------
# Regression — make_chat_handlers' own insert_before must keep working
# ---------------------------------------------------------------------------


def test_make_chat_handlers_insert_before_real_insert(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["insert_before"](
        {"path": "f.py", "pattern": "def foo", "content": "# comment before foo"}
    )
    assert result.startswith("Inserted")
    content = (repo / "f.py").read_text()
    assert "# comment before foo\ndef foo():\n    pass\n" in content


def test_make_chat_handlers_insert_before_rejects_outside_repo_path(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["insert_before"](
        {"path": "/etc/hostname", "pattern": "x", "content": "y"}
    )
    assert result.startswith("[BLOCKED]")
