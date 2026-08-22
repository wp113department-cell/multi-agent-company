"""list_files tool #68 — tool_enhance.md productionization pass
(2026-08-22).

Real, empirically-verified finding, a different shape from tools
#65/#67: `chat_agent.py`'s dispatch called `fp.relative_to(root)`
unguarded inside a generator handed straight to `sorted()` — the first
out-of-repo glob match raised an UNCAUGHT `ValueError`. Through the real
graph-node call path (which wraps every `_execute_tool()` call in a
generic `except Exception`), this didn't crash the turn, but the
resulting error message embedded the ABSOLUTE PATH of a real file
outside the repo — a real, if minor, information-disclosure primitive
the canonical `make_read_only_handlers()` implementation never had (it
already wraps `relative_to()` in try/except).

Despite 79 agents declaring `list_files` in `allowed_tools`, this is
NOT 79 separate implementations — same shape as tools #65/#67.

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
from app.tools.filesystem.list_files import LIST_FILES_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_list_files_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_list_files_tool_schema_has_no_required_fields() -> None:
    assert LIST_FILES_TOOL["name"] == "list_files"
    assert LIST_FILES_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_read_only_tools_index_one_is_still_list_files() -> None:
    """READ_ONLY_TOOLS[1] is indexed positionally elsewhere
    (RESEARCH_TOOLS) — must stay list_files at the same index."""
    assert READ_ONLY_TOOLS[1]["name"] == "list_files"


# ---------------------------------------------------------------------------
# The proven info-leak-via-uncaught-exception finding, verified closed
# on the real dispatch path that had it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_list_files_rejects_directory_outside_repo_cleanly(
    tmp_path: Path,
) -> None:
    """Must return a clean [POLICY DENIED] string, not raise — and the
    message must not leak any real host file path."""
    outside_dir = tmp_path.parent / "list_files_hardening_outside"
    outside_dir.mkdir(exist_ok=True)
    secret_file = outside_dir / "secret_filename.txt"
    secret_file.write_text("x")
    try:
        agent = _agent(tmp_path)
        result = await agent._execute_tool(
            "list_files", {"directory": str(outside_dir)}
        )
        assert result.startswith("[POLICY DENIED]")
        assert "secret_filename.txt" not in result
    finally:
        secret_file.unlink()
        outside_dir.rmdir()


@pytest.mark.asyncio
async def test_chat_agent_list_files_rejects_dotdot_traversal(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "list_files", {"directory": "../../../../../../etc"}
    )
    assert result.startswith("[POLICY DENIED]")


def test_canonical_read_only_handlers_list_files_rejects_directory_outside_repo(
    tmp_path: Path,
) -> None:
    outside_dir = tmp_path.parent / "list_files_hardening_outside2"
    outside_dir.mkdir(exist_ok=True)
    try:
        handlers = make_read_only_handlers(str(tmp_path))
        result = handlers["list_files"]({"directory": str(outside_dir)})
        assert result.startswith("[POLICY DENIED]")
    finally:
        outside_dir.rmdir()


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# both real dispatch paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_list_files_lists_real_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("y")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("list_files", {"pattern": "**/*.py"})
    assert "a.py" in result
    assert "sub/b.py" in result


@pytest.mark.asyncio
async def test_chat_agent_list_files_missing_directory_errors_cleanly(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("list_files", {"directory": "ghost_dir"})
    assert "[ERROR]" in result


def test_canonical_read_only_handlers_lists_real_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["list_files"]({"pattern": "**/*.py"})
    assert "a.py" in result


def test_make_chat_handlers_list_files_lists_real_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["list_files"]({"pattern": "**/*.py"})
    assert "a.py" in result


def test_list_files_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("list_files") == 1
