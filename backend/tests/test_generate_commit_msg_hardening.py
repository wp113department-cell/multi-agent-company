"""generate_commit_msg tool #145 — tool_enhance.md productionization
pass (2026-09-14).

No worktree-escape and no shell-injection risk applies to this tool —
its input schema has only a boolean `staged_only` field, and both real
implementations already used list-args `subprocess.run(["git", ...])`
with no `shell=True` — confirmed via direct code inspection, not
assumed.

One real, empirically-verified finding: a message-accuracy bug on BOTH
real implementations (`make_chat_handlers()`'s `generate_commit_msg`
and `chat_agent.py`'s own separate dispatch). When `staged_only=False`
(checking the UNSTAGED working-tree diff) and there are genuinely no
unstaged changes, the "no changes" error unconditionally said "No
staged changes. Stage files with git_commit or git add first." —
factually backwards in that mode. Proved live against a real,
disposable git repo with a clean working tree.

Fixed via a shared `generate_commit_msg_handler()` in
app/tools/git/generate_commit_msg.py: the "no changes" message is now
conditional on `staged_only`. `_llm_generate_commit_message` (private,
exactly 2 real callers, both belonging to this tool — confirmed via
grep) is left in place and injected as a `generate_fn` callable,
matching tool #136's established dependency-injection pattern.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.generate_commit_msg import (
    GENERATE_COMMIT_MSG_TOOL,
    generate_commit_msg_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_generate_commit_msg_hardening", repo_path=repo)
    return ChatAgent(session)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=str(repo), check=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    (repo / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "a.txt"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), check=True)
    return repo


def test_generate_commit_msg_tool_schema() -> None:
    assert GENERATE_COMMIT_MSG_TOOL["name"] == "generate_commit_msg"
    props = GENERATE_COMMIT_MSG_TOOL["input_schema"]["properties"]  # type: ignore[index]
    assert "staged_only" in props


def test_generate_commit_msg_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("generate_commit_msg") == 1


# ---------------------------------------------------------------------------
# Finding — message-accuracy bug, proved live on a real disposable repo
# ---------------------------------------------------------------------------


def _no_llm(stat: str, diff: str) -> str:
    return ""


class TestMessageAccuracyFix:
    def test_direct_handler_staged_only_true_clean_repo(self, tmp_repo: Path) -> None:
        out = generate_commit_msg_handler(str(tmp_repo), {"staged_only": True}, _no_llm)
        assert "[ERROR]" in out
        assert "No staged changes" in out

    def test_direct_handler_staged_only_false_clean_repo(self, tmp_repo: Path) -> None:
        # This is the exact bug: previously said "No staged changes"
        # even though staged_only=False means we're checking UNSTAGED
        # changes — proved live against a real clean git repo.
        out = generate_commit_msg_handler(
            str(tmp_repo), {"staged_only": False}, _no_llm
        )
        assert "[ERROR]" in out
        assert "No unstaged changes" in out
        assert "No staged changes" not in out

    def test_make_chat_handlers_staged_only_false_clean_repo(
        self, tmp_repo: Path
    ) -> None:
        handlers = make_chat_handlers(str(tmp_repo))
        out = handlers["generate_commit_msg"]({"staged_only": False})
        assert "No unstaged changes" in out
        assert "No staged changes" not in out

    def test_chat_agent_dispatch_staged_only_false_clean_repo(
        self, tmp_repo: Path
    ) -> None:
        agent = _agent(str(tmp_repo))

        async def _run() -> str:
            return await agent._execute_tool(
                "generate_commit_msg", {"staged_only": False}
            )

        import asyncio

        out = asyncio.run(_run())
        assert "No unstaged changes" in out
        assert "No staged changes" not in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real staged/unstaged diffs, both access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_make_chat_handlers_staged_generation(self, tmp_repo: Path) -> None:
        (tmp_repo / "a.txt").write_text("hello\nworld\n")
        subprocess.run(["git", "add", "a.txt"], cwd=str(tmp_repo), check=True)
        handlers = make_chat_handlers(str(tmp_repo))
        with patch(
            "app.agents.tools._llm_generate_commit_message",
            return_value="feat(core): add world line",
        ):
            out = handlers["generate_commit_msg"]({"staged_only": True})
        assert "=== Generated commit message ===" in out
        assert "feat(core): add world line" in out
        assert "a.txt" in out

    def test_make_chat_handlers_falls_back_without_llm(self, tmp_repo: Path) -> None:
        (tmp_repo / "a.txt").write_text("hello\nworld\n")
        subprocess.run(["git", "add", "a.txt"], cwd=str(tmp_repo), check=True)
        handlers = make_chat_handlers(str(tmp_repo))
        with patch("app.agents.tools._llm_generate_commit_message", return_value=""):
            out = handlers["generate_commit_msg"]({"staged_only": True})
        assert "=== Generated commit message ===" not in out
        assert "a.txt" in out

    def test_chat_agent_dispatch_staged_generation(self, tmp_repo: Path) -> None:
        (tmp_repo / "a.txt").write_text("hello\nworld\n")
        subprocess.run(["git", "add", "a.txt"], cwd=str(tmp_repo), check=True)
        agent = _agent(str(tmp_repo))

        async def _run() -> str:
            import app.agents.chat_agent as chat_agent_mod

            with patch.object(
                chat_agent_mod,
                "_llm_generate_commit_message",
                lambda stat, diff: "feat(core): add world line",
            ):
                return await agent._execute_tool(
                    "generate_commit_msg", {"staged_only": True}
                )

        import asyncio

        out = asyncio.run(_run())
        assert "=== Generated commit message ===" in out
        assert "feat(core): add world line" in out
        assert "a.txt" in out

    def test_chat_agent_dispatch_unstaged_generation(self, tmp_repo: Path) -> None:
        (tmp_repo / "a.txt").write_text("hello\nworld\n")
        # NOT staged — real unstaged working-tree change only.
        agent = _agent(str(tmp_repo))

        async def _run() -> str:
            import app.agents.chat_agent as chat_agent_mod

            with patch.object(
                chat_agent_mod,
                "_llm_generate_commit_message",
                lambda stat, diff: "fix(core): tweak a.txt",
            ):
                return await agent._execute_tool(
                    "generate_commit_msg", {"staged_only": False}
                )

        import asyncio

        out = asyncio.run(_run())
        assert "=== Generated commit message ===" in out
        assert "fix(core): tweak a.txt" in out
        assert "a.txt" in out
