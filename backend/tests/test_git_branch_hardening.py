"""git_branch tool #148 — tool_enhance.md productionization pass
(2026-09-14).

One real, empirically-verified finding — a flag-collision bug, the
same class as sibling tools #5's git_reset and #32's create_branch.
Both real implementations (`git_branch` in `make_chat_handlers` +
`chat_agent.py`'s own separate dispatch) built `["git", "branch",
name]` for the `create` action with zero validation that `name`
isn't itself a flag. Proved live against a real disposable git repo:
`git_branch({"action": "create", "name": "--list"})` silently ran
`git branch --list` instead of creating a branch, returning the real
branch listing with no error indication at all.

Fixed via a shared `git_branch_handler()`: `name` is now rejected
outright with a clear `[ERROR]` whenever it starts with `-`, for both
`create` and `delete`.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.branch import GIT_BRANCH_TOOL, git_branch_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_git_branch_hardening", repo_path=repo)
    return ChatAgent(session)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(r), check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(r), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(r), check=True)
    (r / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "a.txt"], cwd=str(r), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(r), check=True)
    return r


def test_git_branch_tool_schema() -> None:
    assert GIT_BRANCH_TOOL["name"] == "git_branch"
    assert GIT_BRANCH_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_git_branch_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("git_branch") == 1


# ---------------------------------------------------------------------------
# Finding — flag-collision bug on the create action, proved live
# ---------------------------------------------------------------------------


class TestFlagCollisionBlocked:
    def test_direct_handler_create_list_flag_rejected(self, repo: Path) -> None:
        out = git_branch_handler(str(repo), {"action": "create", "name": "--list"})
        assert "[ERROR]" in out
        # Must NOT silently list real branches instead of erroring.
        assert "master" not in out and "main" not in out

    def test_direct_handler_create_dash_a_flag_rejected(self, repo: Path) -> None:
        out = git_branch_handler(str(repo), {"action": "create", "name": "-a"})
        assert "[ERROR]" in out

    def test_direct_handler_delete_dash_d_flag_rejected(self, repo: Path) -> None:
        out = git_branch_handler(str(repo), {"action": "delete", "name": "-D"})
        assert "[ERROR]" in out

    def test_make_chat_handlers_create_flag_rejected(self, repo: Path) -> None:
        handlers = make_chat_handlers(str(repo))
        out = handlers["git_branch"]({"action": "create", "name": "--list"})
        assert "[ERROR]" in out

    def test_chat_agent_dispatch_create_flag_rejected(self, repo: Path) -> None:
        agent = _agent(str(repo))

        async def _run() -> str:
            return await agent._execute_tool(
                "git_branch", {"action": "create", "name": "--list"}
            )

        out = asyncio.run(_run())
        assert "[ERROR]" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real branches, both real access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_chat_handlers_create_and_list(self, repo: Path) -> None:
        handlers = make_chat_handlers(str(repo))
        out = handlers["git_branch"]({"action": "create", "name": "feat/real"})
        assert "created" in out.lower()
        listing = handlers["git_branch"]({"action": "list"})
        assert "feat/real" in listing

    def test_make_chat_handlers_delete_real_branch(self, repo: Path) -> None:
        handlers = make_chat_handlers(str(repo))
        handlers["git_branch"]({"action": "create", "name": "to-delete"})
        out = handlers["git_branch"]({"action": "delete", "name": "to-delete"})
        assert "deleted" in out.lower()

    def test_chat_agent_dispatch_create_and_list(self, repo: Path) -> None:
        agent = _agent(str(repo))

        async def _run() -> tuple[str, str]:
            created = await agent._execute_tool(
                "git_branch", {"action": "create", "name": "feat/via-chat"}
            )
            listed = await agent._execute_tool("git_branch", {"action": "list"})
            return created, listed

        created, listed = asyncio.run(_run())
        assert "created" in created.lower()
        assert "feat/via-chat" in listed

    def test_missing_name_still_errors_for_create_and_delete(self, repo: Path) -> None:
        handlers = make_chat_handlers(str(repo))
        assert "name required" in handlers["git_branch"]({"action": "create"})
        assert "name required" in handlers["git_branch"]({"action": "delete"})

    def test_unknown_action_still_errors(self, repo: Path) -> None:
        handlers = make_chat_handlers(str(repo))
        out = handlers["git_branch"]({"action": "bogus"})
        assert "[ERROR] Unknown action" in out
