"""github_comment tool #44 — tool_enhance.md productionization pass
(2026-08-19).

Real finding (scope, not a vulnerability in the handler's own logic):
github_comment had a real, safe handler in make_chat_handlers()
(list-args, no shell=True, number coerced via int()) but was in
neither CHAT_TOOLS nor chat_agent.py's dispatch — zero real agent
could ever reach it, confirmed by grepping the whole repo. Per
explicit user decision (AskUserQuestion, 2026-08-19), this turn wires
it into the interactive chat agent instead of leaving it dead, gated
behind a real confirmation dialog (same pattern as create_pr, since
posting a GitHub comment is a real, publicly-visible external write).

These tests use a fake `gh` script on PATH (never the real GitHub CLI)
so no real, live GitHub comment is ever posted during testing.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.github_comment import (
    GITHUB_COMMENT_TOOL,
    github_comment_command,
)


def _install_fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    gh_script = bin_dir / "gh"
    gh_script.write_text('#!/bin/bash\necho "FAKE_GH_CALLED: $@"\n')
    gh_script.chmod(gh_script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return bin_dir


def _agent(repo: Path, confirm_result: bool) -> ChatAgent:
    session = ChatSession(session_id="td_github_comment_hardening", repo_path=str(repo))
    agent = ChatAgent(session)

    async def _fake_confirm(*_a: object, **_kw: object) -> bool:
        return confirm_result

    agent._confirm = _fake_confirm  # type: ignore[method-assign]
    return agent


def test_github_comment_tool_schema_requires_number_and_body() -> None:
    assert GITHUB_COMMENT_TOOL["name"] == "github_comment"
    assert GITHUB_COMMENT_TOOL["input_schema"]["required"] == ["number", "body"]  # type: ignore[index]


def test_github_comment_is_now_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert "github_comment" in names


# ---------------------------------------------------------------------------
# Pure command-builder tests
# ---------------------------------------------------------------------------


def test_github_comment_command_issue() -> None:
    cmd = github_comment_command(42, "hello", "issue")
    assert cmd == ["gh", "issue", "comment", "42", "--body", "hello"]


def test_github_comment_command_pr() -> None:
    cmd = github_comment_command(7, "lgtm", "pr")
    assert cmd == ["gh", "pr", "comment", "7", "--body", "lgtm"]


def test_github_comment_command_defaults_to_issue_for_unknown_kind() -> None:
    cmd = github_comment_command(1, "x", "bogus")
    assert cmd[1] == "issue"


# ---------------------------------------------------------------------------
# The previously-unreachable tool — now reachable, with a real
# confirmation gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_github_comment_declined_posts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_gh(tmp_path, monkeypatch)
    agent = _agent(tmp_path, confirm_result=False)

    result = await agent._execute_tool(
        "github_comment", {"number": 42, "body": "test comment", "kind": "pr"}
    )
    assert result == "[DENIED] User declined github_comment."


@pytest.mark.asyncio
async def test_chat_agent_github_comment_approved_invokes_real_gh_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_gh(tmp_path, monkeypatch)
    agent = _agent(tmp_path, confirm_result=True)

    result = await agent._execute_tool(
        "github_comment", {"number": 42, "body": "test comment", "kind": "pr"}
    )
    assert "FAKE_GH_CALLED: pr comment 42 --body test comment" in result


@pytest.mark.asyncio
async def test_chat_agent_github_comment_missing_gh_cli(tmp_path: Path) -> None:
    agent = _agent(tmp_path, confirm_result=True)

    # No fake gh installed and PATH untouched — this only works if the
    # real environment has no gh CLI, which is the case in this sandbox;
    # if it ever does, the assertion below simply won't run this branch.
    import shutil

    if shutil.which("gh") is not None:
        pytest.skip("real gh CLI present in this environment")

    result = await agent._execute_tool(
        "github_comment", {"number": 5, "body": "another"}
    )
    assert result == "[ERROR] gh CLI not found"


# ---------------------------------------------------------------------------
# Regression — make_chat_handlers' own github_comment must keep working
# ---------------------------------------------------------------------------


def test_make_chat_handlers_github_comment_real_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_gh(tmp_path, monkeypatch)
    handlers = make_chat_handlers(str(tmp_path))

    result = handlers["github_comment"](
        {"number": 99, "body": "batch agent comment", "kind": "issue"}
    )
    assert "FAKE_GH_CALLED: issue comment 99 --body batch agent comment" in result
