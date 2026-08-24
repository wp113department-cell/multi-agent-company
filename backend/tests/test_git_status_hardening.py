"""git_status tool #79 — tool_enhance.md productionization pass
(2026-08-23).

No security vulnerability — this tool's schema takes zero input, so
there is no LLM-controlled field to audit.

One real, empirically-verified FUNCTIONALITY bug, fixed at the shared
`git_status_handler()` in `app.tools.git.status`: the canonical
`make_read_only_handlers()` implementation silently reported
"(clean)" even when `git status` genuinely failed (never checked
`returncode`). Proved live against a directory that is not a git
repository at all — `chat_agent.py`'s dispatch already surfaced the
real error correctly; the canonical one was the less complete
implementation this time.

All tests here use a real git repository (or real non-repo directory)
on disk — nothing is mocked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    READ_ONLY_TOOLS,
    make_chat_handlers,
    make_read_only_handlers,
)
from app.models.chat import ChatSession
from app.tools.git.status import GIT_STATUS_TOOL


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_git_status_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_git_status_tool_schema_takes_no_input() -> None:
    assert GIT_STATUS_TOOL["name"] == "git_status"
    assert GIT_STATUS_TOOL["input_schema"]["properties"] == {}  # type: ignore[index]


def test_read_only_tools_index_twelve_is_still_git_status() -> None:
    assert READ_ONLY_TOOLS[12]["name"] == "git_status"


# ---------------------------------------------------------------------------
# Finding — canonical implementation silently reported "(clean)" on a
# genuine failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_status_reports_real_error_on_non_repo(
    tmp_path: Path,
) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_status", {})
    assert "[ERROR]" in result
    assert "not a git repository" in result
    assert result != "(clean)"


def test_canonical_read_only_handlers_reports_real_error_on_non_repo(
    tmp_path: Path,
) -> None:
    """The canonical implementation was the one with the real bug this
    time — verify it's now fixed, not just re-confirming chat_agent.py's
    copy (which was already correct)."""
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["git_status"]({})
    assert "[ERROR]" in result
    assert "not a git repository" in result
    assert result != "(clean)"


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all real access paths
# ---------------------------------------------------------------------------


def _real_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("a\n")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return tmp_path


@pytest.mark.asyncio
async def test_chat_agent_git_status_clean_repo_reports_clean(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_status", {})
    assert " M " not in result
    assert "??" not in result


@pytest.mark.asyncio
async def test_chat_agent_git_status_shows_real_modified_file(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    (tmp_path / "a.txt").write_text("modified\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_status", {})
    assert "a.txt" in result
    assert " M a.txt" in result


@pytest.mark.asyncio
async def test_chat_agent_git_status_shows_real_untracked_file(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    (tmp_path / "new_file.txt").write_text("new\n")
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_status", {})
    assert "new_file.txt" in result


def test_canonical_read_only_handlers_shows_real_modified_file(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    (tmp_path / "a.txt").write_text("modified\n")
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["git_status"]({})
    assert " M a.txt" in result


def test_make_chat_handlers_shows_real_modified_file(tmp_path: Path) -> None:
    _real_repo(tmp_path)
    (tmp_path / "a.txt").write_text("modified\n")
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["git_status"]({})
    assert " M a.txt" in result


def test_git_status_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("git_status") == 1
