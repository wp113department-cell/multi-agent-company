"""git_blame tool #81 — tool_enhance.md productionization pass
(2026-08-23).

Same flag-collision root cause class as tool #80's `git_show` (a bare
LLM-controlled positional argv element with no `--` separator), on
BOTH real implementations, fixed at the shared `git_blame_handler()`
in `app.tools.git.blame`. Checked and confirmed LOWER severity than
tool #80: `git blame` has no `--output`-equivalent flag, and its
file-reading flags (`--contents`, `-S`/`--ignore-revs-file`) each
require a separate target-path argument a single `path` value cannot
also supply — proved live, `path="--contents=/etc/passwd"` alone
produces git's own usage error, not a working exploit. Fixed
defensively anyway, matching this initiative's consistent policy.

`path`'s worktree-boundary was checked and confirmed already safe by
construction — git's own `git blame -- <path>` already refuses paths
outside the repository on its own.

All tests here use a real git repository on disk — nothing is mocked.
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
from app.tools.git.blame import GIT_BLAME_TOOL, validate_git_blame_path


def _real_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("line1\nline2\n")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "real commit for tests"], cwd=tmp_path, check=True
    )
    return tmp_path


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_git_blame_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_git_blame_tool_schema_requires_path() -> None:
    assert GIT_BLAME_TOOL["name"] == "git_blame"
    assert GIT_BLAME_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_read_only_tools_index_fourteen_is_still_git_blame() -> None:
    assert READ_ONLY_TOOLS[14]["name"] == "git_blame"


def test_validate_git_blame_path_rejects_flag_shaped_values() -> None:
    assert validate_git_blame_path("--contents=/etc/passwd") is not None
    assert validate_git_blame_path("-S/etc/passwd") is not None
    assert validate_git_blame_path("--porcelain") is not None


def test_validate_git_blame_path_accepts_legitimate_paths() -> None:
    assert validate_git_blame_path("a.txt") is None
    assert validate_git_blame_path("src/app.py") is None


# ---------------------------------------------------------------------------
# Finding — flag-collision on `path` (both real implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_blame_rejects_flag_shaped_path(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_blame", {"path": "--contents=/etc/passwd"})
    assert "[ERROR]" in result


def test_canonical_read_only_handlers_rejects_flag_shaped_path(
    tmp_path: Path,
) -> None:
    """Both real implementations shared the identical shape — verify
    both are fixed, not just chat_agent.py's copy."""
    _real_repo(tmp_path)
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["git_blame"]({"path": "--contents=/etc/passwd"})
    assert "[ERROR]" in result


@pytest.mark.asyncio
async def test_chat_agent_git_blame_rejects_dashdash_path_too(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_blame", {"path": "--porcelain"})
    assert "[ERROR]" in result


# ---------------------------------------------------------------------------
# Checked-safe: worktree boundary (no fix needed, verified as a
# regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_blame_path_outside_repo_is_refused(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_blame", {"path": "/etc/hostname"})
    assert "outside repository" in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_blame_shows_real_blame_output(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_blame", {"path": "a.txt"})
    assert "line1" in result
    assert "line2" in result


@pytest.mark.asyncio
async def test_chat_agent_git_blame_line_range_narrows_output(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "git_blame", {"path": "a.txt", "start_line": 1, "end_line": 1}
    )
    assert "line1" in result
    assert "line2" not in result


def test_canonical_read_only_handlers_shows_real_blame_output(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["git_blame"]({"path": "a.txt"})
    assert "line1" in result


def test_make_chat_handlers_shows_real_blame_output(tmp_path: Path) -> None:
    _real_repo(tmp_path)
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["git_blame"]({"path": "a.txt"})
    assert "line1" in result


def test_git_blame_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("git_blame") == 1
