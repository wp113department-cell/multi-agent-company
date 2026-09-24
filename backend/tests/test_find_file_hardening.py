"""find_file tool #138 — tool_enhance.md productionization pass
(2026-09-11).

One real, severe finding, on BOTH real, byte-identical implementations
(`find_file` inside `make_chat_handlers`, `chat_agent.py`'s own
dispatch): a worktree-boundary escape via `directory`, a genuine
FILENAME/DIRECTORY-STRUCTURE DISCLOSURE oracle (not file content, but
the existence and full paths of files anywhere on the host the process
can read). Proved live: a marker file's real, full absolute path was
genuinely disclosed from a directory entirely outside the intended
worktree.

Both are now closed via a shared `find_file_handler()` using
`check_path_in_worktree()` on `directory`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.filesystem.find_file import FIND_FILE_TOOL, find_file_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_find_file_hardening", repo_path=repo)
    return ChatAgent(session)


def test_find_file_tool_schema() -> None:
    assert FIND_FILE_TOOL["name"] == "find_file"
    assert FIND_FILE_TOOL["input_schema"]["required"] == ["name"]  # type: ignore[index]


def test_find_file_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("find_file") == 1


# ---------------------------------------------------------------------------
# Finding — worktree-escape filename/directory-structure disclosure
# ---------------------------------------------------------------------------


def test_make_chat_handlers_closes_directory_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "SECRET_MARKER.txt"
    marker.write_text("")

    handlers = make_chat_handlers(str(repo))
    result = handlers["find_file"](
        {"name": "SECRET_MARKER.txt", "directory": str(outside)}
    )
    assert "[POLICY DENIED]" in result
    assert "SECRET_MARKER" not in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_closes_directory_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "SECRET_MARKER.txt"
    marker.write_text("")

    agent = _agent(str(repo))
    result = await agent._execute_tool(
        "find_file", {"name": "SECRET_MARKER.txt", "directory": str(outside)}
    )
    assert "[POLICY DENIED]" in result
    assert "SECRET_MARKER" not in result


def test_handler_closes_the_escape_directly(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SECRET_MARKER.txt").write_text("")
    repo = tmp_path / "repo"
    repo.mkdir()

    result = find_file_handler(
        repo, str(repo), {"name": "SECRET_MARKER.txt", "directory": str(outside)}
    )
    assert "[POLICY DENIED]" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working, on both real access
# paths, with and without an explicit directory
# ---------------------------------------------------------------------------


def test_handler_finds_a_real_file(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text("")
    result = find_file_handler(tmp_path, str(tmp_path), {"name": "target.py"})
    assert result == "target.py"


def test_handler_finds_a_real_file_in_a_subdirectory(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "target.py").write_text("")
    result = find_file_handler(
        tmp_path, str(tmp_path), {"name": "target.py", "directory": "sub"}
    )
    assert result == "sub/target.py"


def test_handler_reports_no_matches(tmp_path: Path) -> None:
    result = find_file_handler(
        tmp_path, str(tmp_path), {"name": "nonexistent_xyzzy.py"}
    )
    assert "no files matching" in result


@pytest.mark.asyncio
async def test_chat_agent_dispatch_finds_a_real_file(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text("")
    agent = _agent(str(tmp_path))
    result = await agent._execute_tool("find_file", {"name": "target.py"})
    assert result == "target.py"
