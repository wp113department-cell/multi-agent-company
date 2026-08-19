"""git_restore tool #41 — tool_enhance.md productionization pass
(2026-08-19).

Real, empirically-verified finding (severe — this tool's own schema
description literally reads "This CANNOT be undone", yet neither real
implementation had any protected-path check or confirmation gate):
`chat_agent.py`'s real dispatch discarded real uncommitted content with
zero warning and no way to cancel. Compare to `undo_changes` (a
functionally identical, already-protected sibling tool in this same
file) — `git_restore` was its unprotected twin.
`make_chat_handlers`'s own `git_restore` has the identical gap but,
like `undo_changes_h` before its own fix, is never reachable by any
real one-shot agent — now blocked outright instead of silently
executing an unconfirmed destructive command.

Every test here uses a real git repo and real git subprocess execution,
and proves the fix against the REAL dispatch methods
(ChatAgent._execute_tool and the real make_chat_handlers() handler).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.restore import GIT_RESTORE_TOOL


def _real_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "tracked.txt").write_text("committed content\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def _agent(repo: Path, confirm_result: bool) -> ChatAgent:
    session = ChatSession(session_id="td_git_restore_hardening", repo_path=str(repo))
    agent = ChatAgent(session)

    async def _fake_confirm(*_args: Any, **_kwargs: Any) -> bool:
        return confirm_result

    agent._confirm = _fake_confirm  # type: ignore[method-assign]
    return agent


def test_git_restore_tool_schema_requires_path() -> None:
    assert GIT_RESTORE_TOOL["name"] == "git_restore"
    assert GIT_RESTORE_TOOL["input_schema"]["required"] == ["path"]


# ---------------------------------------------------------------------------
# The proven missing-confirmation-gate finding — verified closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_restore_declined_confirmation_preserves_content(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    (repo / "tracked.txt").write_text("committed content\nuncommitted change\n")
    agent = _agent(repo, confirm_result=False)

    result = await agent._execute_tool("git_restore", {"path": "tracked.txt"})
    assert result.startswith("[CANCELLED]")
    assert (
        repo / "tracked.txt"
    ).read_text() == "committed content\nuncommitted change\n"


@pytest.mark.asyncio
async def test_chat_agent_git_restore_approved_confirmation_discards_content(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    (repo / "tracked.txt").write_text("committed content\nuncommitted change\n")
    agent = _agent(repo, confirm_result=True)

    result = await agent._execute_tool("git_restore", {"path": "tracked.txt"})
    assert not result.startswith("[ERROR]")
    assert (repo / "tracked.txt").read_text() == "committed content\n"


def test_make_chat_handlers_git_restore_is_blocked(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    (repo / "tracked.txt").write_text("committed content\nuncommitted change\n")
    handlers = make_chat_handlers(str(repo))

    result = handlers["git_restore"]({"path": "tracked.txt"})
    assert result.startswith("[BLOCKED]")
    assert (
        repo / "tracked.txt"
    ).read_text() == "committed content\nuncommitted change\n"


@pytest.mark.asyncio
async def test_chat_agent_git_restore_rejects_protected_path(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo, confirm_result=True)

    result = await agent._execute_tool("git_restore", {"path": ".env"})
    assert result.startswith("[POLICY DENIED]")


def test_make_chat_handlers_git_restore_rejects_protected_path(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["git_restore"]({"path": ".env"})
    assert result.startswith("[POLICY DENIED]")


# ---------------------------------------------------------------------------
# Regression — unstaging (non-destructive) must NOT require confirmation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_restore_staged_unstage_needs_no_confirmation(
    tmp_path: Path,
) -> None:
    repo = _real_repo(tmp_path)
    (repo / "tracked.txt").write_text("staged change\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)

    session = ChatSession(session_id="td_git_restore_unstage", repo_path=str(repo))
    agent = ChatAgent(session)

    async def _fail_if_called(*_args: Any, **_kwargs: Any) -> bool:
        raise AssertionError("confirmation should not be requested for staged=True")

    agent._confirm = _fail_if_called  # type: ignore[method-assign]

    result = await agent._execute_tool(
        "git_restore", {"path": "tracked.txt", "staged": True}
    )
    assert not result.startswith("[ERROR]")

    status = subprocess.run(
        ["git", "status", "--short"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert " M tracked.txt" in status
    assert (repo / "tracked.txt").read_text() == "staged change\n"


@pytest.mark.asyncio
async def test_chat_agent_git_restore_file_not_found(tmp_path: Path) -> None:
    repo = _real_repo(tmp_path)
    agent = _agent(repo, confirm_result=True)

    result = await agent._execute_tool("git_restore", {"path": "nonexistent.txt"})
    assert result.startswith("[ERROR]")
