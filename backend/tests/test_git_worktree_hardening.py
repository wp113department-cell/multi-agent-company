"""git_worktree tool #43 — tool_enhance.md productionization pass
(2026-08-19).

Real, empirically-verified findings:

1. Severe — an arbitrary-filesystem-write-anywhere primitive (same
   severity class as tool #18's docker_build host-file finding):
   neither implementation restricted where `git worktree add` could
   write. Proved live: a real worktree (a full checkout of a branch's
   tree) was planted at an arbitrary absolute path with zero
   confirmation, zero warning.
2. Flag/positional-shifting confusion (a variant of the flag-collision
   class from tools #5/#32/#35/#36/#38/#39/#40/#41): a flag-shaped
   `path` caused git to silently reinterpret `branch`'s value as the
   destination path instead of erroring cleanly.

Ruled out: `git worktree remove` already refuses (without --force,
never passed here) if the worktree has modified/untracked files — no
silent data loss possible through this tool.

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
from app.tools.git.worktree import GIT_WORKTREE_TOOL, validate_git_worktree_inputs


def _real_repo_with_branch(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@a.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=repo, check=True)
    (repo / "f.txt").write_text("base\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "feature"], cwd=repo, check=True)
    return repo


def _agent(repo: Path, confirm_result: bool) -> ChatAgent:
    session = ChatSession(session_id="td_git_worktree_hardening", repo_path=str(repo))
    agent = ChatAgent(session)

    async def _fake_confirm(*_args: Any, **_kwargs: Any) -> bool:
        return confirm_result

    agent._confirm = _fake_confirm  # type: ignore[method-assign]
    return agent


def test_git_worktree_tool_schema_has_enum() -> None:
    assert GIT_WORKTREE_TOOL["name"] == "git_worktree"
    assert set(GIT_WORKTREE_TOOL["input_schema"]["properties"]["action"]["enum"]) == {
        "list",
        "add",
        "remove",
    }


# ---------------------------------------------------------------------------
# Pure validator tests
# ---------------------------------------------------------------------------


def test_validator_rejects_flag_shaped_path_and_branch() -> None:
    assert validate_git_worktree_inputs("add", "-f", "feature") is not None
    assert validate_git_worktree_inputs("add", "/tmp/x", "--force") is not None


def test_validator_requires_path_and_branch_for_add() -> None:
    assert validate_git_worktree_inputs("add", "", "feature") is not None
    assert validate_git_worktree_inputs("add", "/tmp/x", "") is not None
    assert validate_git_worktree_inputs("add", "/tmp/x", "feature") is None


def test_validator_requires_path_for_remove() -> None:
    assert validate_git_worktree_inputs("remove", "", "") is not None
    assert validate_git_worktree_inputs("remove", "/tmp/x", "") is None


def test_validator_allows_list_with_no_extra_fields() -> None:
    assert validate_git_worktree_inputs("list", "", "") is None


# ---------------------------------------------------------------------------
# The proven arbitrary-path-write finding — verified closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_worktree_add_declined_confirmation_creates_nothing(
    tmp_path: Path,
) -> None:
    repo = _real_repo_with_branch(tmp_path)
    wt_path = tmp_path / "outside_worktree"
    agent = _agent(repo, confirm_result=False)

    result = await agent._execute_tool(
        "git_worktree", {"action": "add", "path": str(wt_path), "branch": "feature"}
    )
    assert result.startswith("[CANCELLED]")
    assert not wt_path.exists()


@pytest.mark.asyncio
async def test_chat_agent_git_worktree_add_approved_confirmation_creates_real_worktree(
    tmp_path: Path,
) -> None:
    repo = _real_repo_with_branch(tmp_path)
    wt_path = tmp_path / "outside_worktree2"
    agent = _agent(repo, confirm_result=True)

    result = await agent._execute_tool(
        "git_worktree", {"action": "add", "path": str(wt_path), "branch": "feature"}
    )
    assert not result.startswith("[ERROR]")
    assert wt_path.exists()
    assert (wt_path / "f.txt").exists()


def test_make_chat_handlers_git_worktree_add_is_blocked(tmp_path: Path) -> None:
    repo = _real_repo_with_branch(tmp_path)
    wt_path = tmp_path / "should_not_exist"
    handlers = make_chat_handlers(str(repo))

    result = handlers["git_worktree"](
        {"action": "add", "path": str(wt_path), "branch": "feature"}
    )
    assert result.startswith("[BLOCKED]")
    assert not wt_path.exists()


# ---------------------------------------------------------------------------
# The proven flag/positional-shifting finding — verified closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_worktree_rejects_flag_shaped_path(
    tmp_path: Path,
) -> None:
    repo = _real_repo_with_branch(tmp_path)
    agent = _agent(repo, confirm_result=True)

    result = await agent._execute_tool(
        "git_worktree", {"action": "add", "path": "-f", "branch": "feature"}
    )
    assert result.startswith("[ERROR]")
    assert not (repo / "feature").exists()


# ---------------------------------------------------------------------------
# Regression — list and remove must keep working exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_git_worktree_list_and_remove(tmp_path: Path) -> None:
    repo = _real_repo_with_branch(tmp_path)
    wt_path = tmp_path / "removable_worktree"
    agent = _agent(repo, confirm_result=True)

    add_result = await agent._execute_tool(
        "git_worktree", {"action": "add", "path": str(wt_path), "branch": "feature"}
    )
    assert not add_result.startswith("[ERROR]")

    list_result = await agent._execute_tool("git_worktree", {"action": "list"})
    assert str(wt_path) in list_result

    remove_result = await agent._execute_tool(
        "git_worktree", {"action": "remove", "path": str(wt_path)}
    )
    assert not remove_result.startswith("[ERROR]")
    assert not wt_path.exists()


def test_make_chat_handlers_git_worktree_list_works(tmp_path: Path) -> None:
    repo = _real_repo_with_branch(tmp_path)
    handlers = make_chat_handlers(str(repo))

    result = handlers["git_worktree"]({"action": "list"})
    assert str(repo) in result
