"""github_create_issue tool #45 — tool_enhance.md productionization
pass (2026-08-19).

Real finding: same "advertised but never dispatched" bug class as
tools #4/#6/#22/#25/#33/#44 — github_create_issue was already in
CHAT_TOOLS ("Day 3G — External integrations" section) with a fully-
implemented, already-safe make_chat_handlers() handler (list-args, no
shell=True), but chat_agent.py had zero dispatch branch for it — every
real interactive call would have hit "[ERROR] Unknown tool".

These tests use a fake `gh` script on PATH (never the real GitHub CLI)
so no real, live GitHub issue is ever created during testing.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.git.github_create_issue import (
    GITHUB_CREATE_ISSUE_TOOL,
    github_create_issue_command,
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
    session = ChatSession(
        session_id="td_github_create_issue_hardening", repo_path=str(repo)
    )
    agent = ChatAgent(session)

    async def _fake_confirm(*_a: object, **_kw: object) -> bool:
        return confirm_result

    agent._confirm = _fake_confirm  # type: ignore[method-assign]
    return agent


def test_github_create_issue_tool_schema_requires_title_and_body() -> None:
    assert GITHUB_CREATE_ISSUE_TOOL["name"] == "github_create_issue"
    assert GITHUB_CREATE_ISSUE_TOOL["input_schema"]["required"] == ["title", "body"]  # type: ignore[index]


def test_github_create_issue_is_in_chat_tools_exactly_once() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("github_create_issue") == 1


# ---------------------------------------------------------------------------
# Pure command-builder tests
# ---------------------------------------------------------------------------


def test_github_create_issue_command_no_labels() -> None:
    cmd = github_create_issue_command("Bug", "desc", [])
    assert cmd == ["gh", "issue", "create", "--title", "Bug", "--body", "desc"]


def test_github_create_issue_command_with_labels() -> None:
    cmd = github_create_issue_command("Bug", "desc", ["bug", "urgent"])
    assert cmd == [
        "gh", "issue", "create", "--title", "Bug", "--body", "desc",
        "--label", "bug", "--label", "urgent",
    ]


# ---------------------------------------------------------------------------
# The previously-unreachable tool — now reachable, with a real
# confirmation gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_github_create_issue_declined_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_gh(tmp_path, monkeypatch)
    agent = _agent(tmp_path, confirm_result=False)

    result = await agent._execute_tool(
        "github_create_issue", {"title": "Bug", "body": "desc", "labels": ["bug"]}
    )
    assert result == "[DENIED] User declined github_create_issue."


@pytest.mark.asyncio
async def test_chat_agent_github_create_issue_approved_invokes_real_gh_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_gh(tmp_path, monkeypatch)
    agent = _agent(tmp_path, confirm_result=True)

    result = await agent._execute_tool(
        "github_create_issue",
        {"title": "Bug", "body": "desc", "labels": ["bug", "urgent"]},
    )
    assert (
        "FAKE_GH_CALLED: issue create --title Bug --body desc --label bug --label urgent"
        in result
    )


@pytest.mark.asyncio
async def test_chat_agent_github_create_issue_missing_gh_cli(tmp_path: Path) -> None:
    import shutil

    if shutil.which("gh") is not None:
        pytest.skip("real gh CLI present in this environment")

    agent = _agent(tmp_path, confirm_result=True)
    result = await agent._execute_tool(
        "github_create_issue", {"title": "Bug", "body": "desc"}
    )
    assert result == "[ERROR] gh CLI not found — install GitHub CLI"


# ---------------------------------------------------------------------------
# Regression — make_chat_handlers' own github_create_issue must keep
# working
# ---------------------------------------------------------------------------


def test_make_chat_handlers_github_create_issue_real_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_gh(tmp_path, monkeypatch)
    handlers = make_chat_handlers(str(tmp_path))

    result = handlers["github_create_issue"](
        {"title": "Batch issue", "body": "batch body", "labels": []}
    )
    assert "FAKE_GH_CALLED: issue create --title Batch issue --body batch body" in result
