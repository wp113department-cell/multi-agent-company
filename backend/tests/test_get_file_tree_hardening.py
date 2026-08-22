"""get_file_tree tool #67 — tool_enhance.md productionization pass
(2026-08-22).

Real, empirically-verified finding: `chat_agent.py`'s real dispatch had
ZERO worktree-boundary validation on `directory` (unlike the canonical
`make_read_only_handlers()` implementation, used by every
`run_agent_graph`-based agent and by `make_chat_handlers`). Proved
live: `get_file_tree({"directory": "/etc"})` through
`ChatAgent._execute_tool` genuinely returned the real directory
structure of `/etc` — an information-disclosure primitive.

Despite 79 agents declaring `get_file_tree` in `allowed_tools`, this is
NOT 79 separate implementations — same shape as tool #65 (`read_file`).

All tests here use real directories on disk — nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    READ_ONLY_TOOLS,
    make_chat_handlers,
    make_read_only_handlers,
)
from app.models.chat import ChatSession
from app.tools.filesystem.get_file_tree import GET_FILE_TREE_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_get_file_tree_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_get_file_tree_tool_schema_has_no_required_fields() -> None:
    assert GET_FILE_TREE_TOOL["name"] == "get_file_tree"
    assert GET_FILE_TREE_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_read_only_tools_index_four_is_still_get_file_tree() -> None:
    """READ_ONLY_TOOLS[4] is indexed positionally elsewhere
    (RESEARCH_TOOLS) — must stay get_file_tree at the same index."""
    assert READ_ONLY_TOOLS[4]["name"] == "get_file_tree"


# ---------------------------------------------------------------------------
# The proven worktree-escape finding, verified closed on the real
# dispatch path that lacked protection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_get_file_tree_rejects_directory_outside_repo(
    tmp_path: Path,
) -> None:
    outside_dir = tmp_path.parent / "get_file_tree_hardening_outside"
    outside_dir.mkdir(exist_ok=True)
    (outside_dir / "secret.txt").write_text("secret")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "get_file_tree", {"directory": str(outside_dir)}
        )
        assert "[POLICY DENIED]" in result
        assert "secret.txt" not in result
    finally:
        (outside_dir / "secret.txt").unlink()
        outside_dir.rmdir()


@pytest.mark.asyncio
async def test_chat_agent_get_file_tree_rejects_dotdot_traversal(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "get_file_tree", {"directory": "../../../../../../etc"}
    )
    assert "[POLICY DENIED]" in result


def test_canonical_read_only_handlers_still_rejects_directory_outside_repo(
    tmp_path: Path,
) -> None:
    outside_dir = tmp_path.parent / "get_file_tree_hardening_outside2"
    outside_dir.mkdir(exist_ok=True)
    try:
        handlers = make_read_only_handlers(str(tmp_path))
        result = handlers["get_file_tree"]({"directory": str(outside_dir)})
        assert "[POLICY DENIED]" in result
    finally:
        outside_dir.rmdir()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_get_file_tree_lists_real_directory(
    tmp_path: Path,
) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.txt").write_text("x")
    (tmp_path / "top.txt").write_text("y")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("get_file_tree", {})
    assert "sub" in result
    assert "nested.txt" in result
    assert "top.txt" in result


@pytest.mark.asyncio
async def test_chat_agent_get_file_tree_missing_directory_errors_cleanly(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("get_file_tree", {"directory": "ghost_dir"})
    assert "[ERROR]" in result


def test_canonical_read_only_handlers_lists_real_directory(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.txt").write_text("x")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["get_file_tree"]({})
    assert "sub" in result
    assert "nested.txt" in result


def test_make_chat_handlers_get_file_tree_lists_real_directory(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["get_file_tree"]({})
    assert "sub" in result


def test_max_depth_still_clamps_to_four(tmp_path: Path) -> None:
    handlers = make_read_only_handlers(str(tmp_path))
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b").mkdir()
    (tmp_path / "a" / "b" / "c").mkdir()
    (tmp_path / "a" / "b" / "c" / "d").mkdir()
    (tmp_path / "a" / "b" / "c" / "d" / "e").mkdir()
    (tmp_path / "a" / "b" / "c" / "d" / "e" / "too_deep.txt").write_text("x")
    result = handlers["get_file_tree"]({"max_depth": 99})
    assert "too_deep.txt" not in result


def test_get_file_tree_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("get_file_tree") == 1
