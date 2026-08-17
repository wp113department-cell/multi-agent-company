"""github_create_pr tool #6 — tool_enhance.md productionization pass
(2026-08-16).

Real findings, each with a direct test here:
1. `github_create_pr` is advertised to the interactive chat LLM via
   CHAT_TOOLS/AGENT_CONTRACT["allowed_tools"] (confirmed: `_GITHUB_CREATE_PR_TOOL`
   is part of the CHAT_TOOLS list chat_agent's own contract is built
   from), but chat_agent.py's `_execute_tool` had NO dispatch branch for
   it at all — every real call fell through to a generic "[ERROR] Unknown
   tool: github_create_pr" response. Same live bug class as
   npm_install/npm_run/pip_install from tool #4.
2. `github_create_pr` was a second, separately-maintained implementation
   of the exact same real action as create_pr (both just run
   `gh pr create`) — with none of create_pr's hardening from tool #2's
   two passes (repo/branch/base identity verification, no-diff guard,
   duplicate-PR check, fail-closed approval gate, output sanitization,
   real PR-URL extraction). Both real call sites now delegate to the
   same, already-hardened create_pr_handler / chat_agent.py dispatch
   block instead of duplicating that hardening a second time.

Tests prove BOTH the missing-dispatch fix and that the delegation is
real (not just a superficial rename) — i.e. create_pr's own hardening
genuinely applies when called via the github_create_pr name too.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.chat_agent import AGENT_CONTRACT, ChatAgent
from app.agents.tools import make_chat_handlers
from app.config import get_settings
from app.models.chat import ChatSession


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "a.txt").write_text("a")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True)
    return repo


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(session_id="td_ghpr_hardening", repo_path=str(repo))
    return ChatAgent(session)


def _add_bare_origin(repo: Path, parent: Path) -> None:
    bare = parent / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=repo, check=True)
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=repo, check=True)


# ---------------------------------------------------------------------------
# 1. Premise check + the real dispatch bug
# ---------------------------------------------------------------------------


def test_github_create_pr_is_really_advertised_to_the_chat_llm() -> None:
    """Confirms the real premise: this tool WAS reachable/advertised, so
    the missing dispatch was a live bug, not dead code."""
    assert "github_create_pr" in AGENT_CONTRACT["allowed_tools"]


@pytest.mark.asyncio
async def test_github_create_pr_was_previously_unknown_tool_now_dispatches(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    agent = _agent(repo)
    with patch.object(
        agent, "_confirm", new=AsyncMock(return_value=False)
    ) as mock_confirm:
        result = await agent._execute_tool(
            "github_create_pr", {"title": "Add feature", "body": "Does the thing."}
        )

    mock_confirm.assert_awaited_once()
    assert result != "[ERROR] Unknown tool: github_create_pr"
    assert "[DENIED]" in result


@pytest.mark.asyncio
async def test_github_create_pr_runs_for_real_when_approved(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    agent = _agent(repo)
    with (
        patch.object(agent, "_confirm", new=AsyncMock(return_value=True)),
        patch("app.agents.chat_agent._run_subprocess", return_value="ok") as mock_run,
    ):
        result = await agent._execute_tool(
            "github_create_pr", {"title": "Add feature", "body": "Does the thing."}
        )

    mock_run.assert_called_once()
    assert result == "ok"


# ---------------------------------------------------------------------------
# 2. Delegation to create_pr_handler is real, not superficial — its
# hardening genuinely applies under the github_create_pr name too.
# ---------------------------------------------------------------------------


def test_tools_py_handler_delegates_to_the_same_fail_closed_approval_gate(
    tmp_path: Path,
) -> None:
    """create_pr_require_approval is real and shared — no separate
    github_create_pr_require_approval flag was invented."""
    repo = _git_repo(tmp_path)
    handlers = make_chat_handlers(str(repo))
    result = handlers["github_create_pr"]({"title": "x", "body": "y"})
    assert result.startswith("[POLICY DENIED]")
    assert "human approval" in result


def test_tools_py_handler_applies_the_real_no_diff_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real proof the delegation isn't cosmetic: create_pr_handler's
    no-diff guard (tool #2's second pass) fires for github_create_pr too
    — a branch with zero real changes against base is refused."""
    monkeypatch.setattr(get_settings(), "create_pr_require_approval", False)
    repo = _git_repo(tmp_path)
    _add_bare_origin(repo, tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    handlers = make_chat_handlers(str(repo))

    with (
        patch("app.tools.git.pull_request.check_gh_auth", return_value=None),
        patch(
            "app.tools.git.pull_request.resolve_repository_identity",
            return_value=(None, "test/repo"),
        ),
    ):
        result = handlers["github_create_pr"](
            {"title": "x", "body": "y", "base": "main"}
        )

    assert "No changes available" in result


def test_tools_py_handler_applies_the_real_branch_safety_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another real create_pr_handler check (current branch == base is
    refused) proven to genuinely apply under this tool's name too."""
    monkeypatch.setattr(get_settings(), "create_pr_require_approval", False)
    repo = _git_repo(tmp_path)  # current branch is 'main'
    handlers = make_chat_handlers(str(repo))

    with (
        patch("app.tools.git.pull_request.check_gh_auth", return_value=None),
        patch(
            "app.tools.git.pull_request.resolve_repository_identity",
            return_value=(None, "test/repo"),
        ),
    ):
        result = handlers["github_create_pr"](
            {"title": "x", "body": "y", "base": "main"}
        )

    assert "refusing to open a PR from a branch into itself" in result
