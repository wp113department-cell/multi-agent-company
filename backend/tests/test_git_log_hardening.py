"""git_log tool #78 — tool_enhance.md productionization pass
(2026-08-23).

One real, empirically-verified finding, fixed at the shared
`git_log_handler()` in `app.tools.git.log`:

An uncaught `ValueError` on a non-numeric `count`, on BOTH real
implementations. Proved live: `git_log({"count": "not_a_number"})`
raised `ValueError` uncaught through both `chat_agent.py`'s real
dispatch and the canonical `make_read_only_handlers()` factory.

`file` was checked and confirmed already safe by construction: a `--`
pathspec separator (verified live with `file="--force"`, harmless) and
git's own outside-repository refusal (verified live with
`file="/etc/passwd"` and a `../../../etc/passwd` traversal, both
refused by git itself) — no fix needed there.

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
from app.tools.git.log import GIT_LOG_TOOL


def _real_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("a\n")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "first real commit"], cwd=tmp_path, check=True
    )
    return tmp_path


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_git_log_hardening", repo_path=str(repo))
    return ChatAgent(session)


def test_git_log_tool_schema_has_no_required_fields() -> None:
    assert GIT_LOG_TOOL["name"] == "git_log"
    assert GIT_LOG_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_read_only_tools_index_five_is_still_git_log() -> None:
    assert READ_ONLY_TOOLS[5]["name"] == "git_log"


# ---------------------------------------------------------------------------
# Finding — uncaught ValueError on non-numeric count (both real
# implementations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_log_handles_non_numeric_count_gracefully(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_log", {"count": "not_a_number"})
    assert result.startswith("[ERROR]")  # must not raise


def test_canonical_read_only_handlers_handles_non_numeric_count_gracefully(
    tmp_path: Path,
) -> None:
    """Both real implementations shared the identical bug — verify both
    are fixed, not just chat_agent.py's copy."""
    _real_repo(tmp_path)
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["git_log"]({"count": "not_a_number"})
    assert result.startswith("[ERROR]")  # must not raise


@pytest.mark.asyncio
async def test_chat_agent_git_log_handles_list_count_gracefully(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_log", {"count": [1, 2]})
    assert result.startswith("[ERROR]")  # must not raise (TypeError case)


# ---------------------------------------------------------------------------
# Checked-safe: file (no fix needed, verified as a regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_log_file_outside_repo_is_refused(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_log", {"file": "/etc/passwd"})
    assert "[ERROR]" in result
    assert "outside repository" in result


@pytest.mark.asyncio
async def test_chat_agent_git_log_flag_shaped_file_is_harmless(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_log", {"file": "--force"})
    assert "[ERROR]" not in result


# ---------------------------------------------------------------------------
# Regression — legitimate usage must keep working exactly as before, on
# all real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_log_shows_real_commit(tmp_path: Path) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_log", {})
    assert "first real commit" in result


def test_canonical_read_only_handlers_shows_real_commit(tmp_path: Path) -> None:
    _real_repo(tmp_path)
    handlers = make_read_only_handlers(str(tmp_path))
    result = handlers["git_log"]({})
    assert "first real commit" in result


def test_make_chat_handlers_shows_real_commit(tmp_path: Path) -> None:
    _real_repo(tmp_path)
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["git_log"]({})
    assert "first real commit" in result


@pytest.mark.asyncio
async def test_chat_agent_git_log_count_clamped_to_max_30(tmp_path: Path) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_log", {"count": 9999})
    assert "[ERROR]" not in result


@pytest.mark.asyncio
async def test_chat_agent_git_log_zero_count_clamped_to_minimum_one(
    tmp_path: Path,
) -> None:
    _real_repo(tmp_path)
    agent = _agent(tmp_path)
    result = await agent._execute_tool("git_log", {"count": 0})
    assert "first real commit" in result


def test_git_log_appears_exactly_once_in_chat_tools() -> None:
    from app.agents.tools import CHAT_TOOLS

    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("git_log") == 1
