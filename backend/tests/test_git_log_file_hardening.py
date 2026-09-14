"""git_log_file tool #150 — tool_enhance.md productionization pass
(2026-09-14).

Two real, empirically-verified findings on the one real
implementation (`git_log_file_h` inside `make_chat_handlers`).

1. Worktree-boundary escape — a genuine COMMIT-HISTORY DISCLOSURE
   oracle. `path` was passed straight to `git log -- <path>` with no
   validation it stayed inside the intended worktree. Proved live:
   with the intended worktree set to a subdirectory of a larger real
   git repository, `git_log_file({"path": "../secret.txt"})` genuinely
   disclosed real commit hashes AND commit messages for a file outside
   the intended worktree.
2. Advertised in CHAT_TOOLS but never dispatched by chat_agent.py —
   every real interactive-chat call fell through to "[ERROR] Unknown
   tool: git_log_file".

Both are now closed via a shared `git_log_file_handler()` using
`check_path_in_worktree()` on `path`.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.log_file import GIT_LOG_FILE_TOOL, git_log_file_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_git_log_file_hardening", repo_path=repo)
    return ChatAgent(session)


@pytest.fixture
def nested_repo(tmp_path: Path) -> Path:
    """A real git repo where the intended worktree is a SUBDIRECTORY,
    and a secret file lives outside it (in the parent), inside the
    same git repository history — the exact scenario that made the
    real escape possible."""
    parent = tmp_path / "parent"
    subdir = parent / "subdir"
    subdir.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=str(parent), check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(parent), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(parent), check=True)
    (subdir / "public.txt").write_text("public content\n")
    (parent / "secret.txt").write_text("SECRET_API_KEY=abc123\n")
    subprocess.run(
        ["git", "add", "subdir/public.txt", "secret.txt"], cwd=str(parent), check=True
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial commit with secret.txt"],
        cwd=str(parent),
        check=True,
    )
    (parent / "secret.txt").write_text("SECRET_API_KEY=abc123\nmore secret info\n")
    subprocess.run(["git", "add", "secret.txt"], cwd=str(parent), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "update secret.txt with more secret info"],
        cwd=str(parent),
        check=True,
    )
    return subdir


def test_git_log_file_tool_schema() -> None:
    assert GIT_LOG_FILE_TOOL["name"] == "git_log_file"
    assert GIT_LOG_FILE_TOOL["input_schema"]["required"] == ["path"]  # type: ignore[index]


def test_git_log_file_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("git_log_file") == 1


# ---------------------------------------------------------------------------
# Finding #1 — worktree-escape commit-history disclosure
# ---------------------------------------------------------------------------


class TestWorktreeEscapeBlocked:
    def test_direct_handler_escape_blocked(self, nested_repo: Path) -> None:
        out = git_log_file_handler(str(nested_repo), {"path": "../secret.txt"})
        assert "POLICY DENIED" in out
        assert "secret info" not in out
        assert "update secret.txt" not in out

    def test_make_chat_handlers_escape_blocked(self, nested_repo: Path) -> None:
        handlers = make_chat_handlers(str(nested_repo))
        out = handlers["git_log_file"]({"path": "../secret.txt"})
        assert "POLICY DENIED" in out
        assert "update secret.txt" not in out

    def test_chat_agent_dispatch_escape_blocked(self, nested_repo: Path) -> None:
        agent = _agent(str(nested_repo))

        async def _run() -> str:
            return await agent._execute_tool(
                "git_log_file", {"path": "../secret.txt"}
            )

        out = asyncio.run(_run())
        assert "POLICY DENIED" in out
        assert "update secret.txt" not in out

    def test_absolute_path_escape_blocked(self, nested_repo: Path) -> None:
        secret_abs = str(nested_repo.parent / "secret.txt")
        out = git_log_file_handler(str(nested_repo), {"path": secret_abs})
        assert "POLICY DENIED" in out


# ---------------------------------------------------------------------------
# Finding #2 — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(
        self, nested_repo: Path
    ) -> None:
        agent = _agent(str(nested_repo))

        async def _run() -> str:
            return await agent._execute_tool(
                "git_log_file", {"path": "public.txt"}
            )

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "initial commit with secret.txt" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real in-worktree file, both access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_chat_handlers_real_commit_history(self, nested_repo: Path) -> None:
        handlers = make_chat_handlers(str(nested_repo))
        out = handlers["git_log_file"]({"path": "public.txt"})
        assert "initial commit with secret.txt" in out

    def test_limit_respected(self, nested_repo: Path) -> None:
        subprocess.run(
            ["git", "commit", "--allow-empty", "-q", "-m", "extra commit 1"],
            cwd=str(nested_repo),
            check=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-q", "-m", "extra commit 2"],
            cwd=str(nested_repo),
            check=True,
        )
        handlers = make_chat_handlers(str(nested_repo))
        out = handlers["git_log_file"]({"path": "public.txt", "limit": 1})
        assert out.count("\n") == 0

    def test_no_commits_found_for_untracked_file(self, nested_repo: Path) -> None:
        (nested_repo / "untracked.txt").write_text("x\n")
        handlers = make_chat_handlers(str(nested_repo))
        out = handlers["git_log_file"]({"path": "untracked.txt"})
        assert "no commits found" in out
