"""git_stash_list tool #151 — tool_enhance.md productionization pass
(2026-09-14).

The input schema is empty (no properties at all) — no LLM-controlled
input reaches this tool, so the worktree-boundary-escape and
shell-injection classes established repeatedly this initiative do not
apply.

One real, empirically-verified finding — advertised in CHAT_TOOLS but
never dispatched by chat_agent.py. Proved live: a real git repo with
a real stash on it, called through the real chat_agent.py dispatch,
returned "[ERROR] Unknown tool: git_stash_list" instead of listing the
stash.

Fixed via a shared git_stash_list_handler(); a new chat_agent.py
dispatch branch delegates to it.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.stash_list import GIT_STASH_LIST_TOOL, git_stash_list_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_git_stash_list_hardening", repo_path=repo)
    return ChatAgent(session)


@pytest.fixture
def repo_with_stash(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(r), check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(r), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(r), check=True)
    (r / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "a.txt"], cwd=str(r), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(r), check=True)
    (r / "a.txt").write_text("changed\n")
    subprocess.run(
        ["git", "stash", "push", "-q", "-m", "wip stash"], cwd=str(r), check=True
    )
    return r


def test_git_stash_list_tool_schema() -> None:
    assert GIT_STASH_LIST_TOOL["name"] == "git_stash_list"
    assert GIT_STASH_LIST_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_git_stash_list_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("git_stash_list") == 1


# ---------------------------------------------------------------------------
# Finding — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(
        self, repo_with_stash: Path
    ) -> None:
        agent = _agent(str(repo_with_stash))

        async def _run() -> str:
            return await agent._execute_tool("git_stash_list", {})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "wip stash" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real stash, both real access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_lists_real_stash(self, repo_with_stash: Path) -> None:
        out = git_stash_list_handler(str(repo_with_stash))
        assert "wip stash" in out

    def test_make_chat_handlers_lists_real_stash(self, repo_with_stash: Path) -> None:
        handlers = make_chat_handlers(str(repo_with_stash))
        out = handlers["git_stash_list"]({})
        assert "wip stash" in out

    def test_no_stashes_message(self, tmp_path: Path) -> None:
        r = tmp_path / "clean_repo"
        r.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=str(r), check=True)
        out = git_stash_list_handler(str(r))
        assert out == "(no stashes)"
