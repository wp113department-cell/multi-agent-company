"""github_inspect_repo tool #152 — tool_enhance.md productionization
pass (2026-09-14).

`owner`/`repo`/`path` reach a `https://api.github.com/...` URL this
tool builds itself — checked directly and CONFIRMED already safe:
validated against `^[A-Za-z0-9._-]+$` (rejecting URL-structural
characters like `/`, `@`, `:`), and `path` segments additionally
reject `.`/`..`. Proved live: an injection attempt via `owner` and a
path-traversal attempt via `path` were both rejected — no fix needed
there.

One real, empirically-verified finding — advertised in CHAT_TOOLS but
never dispatched by chat_agent.py. Proved live: a real call through
the real chat_agent.py dispatch for a real public GitHub repo
(octocat/Hello-World) returned "[ERROR] Unknown tool:
github_inspect_repo" instead of the real repo metadata.

Fixed via a shared github_inspect_repo_handler(); a new chat_agent.py
dispatch branch delegates to it.

Tests marked slow make a real, unauthenticated network call to the
real GitHub REST API.
"""

from __future__ import annotations

import asyncio

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.integrations.github_inspect_repo import (
    GITHUB_INSPECT_REPO_TOOL,
    github_inspect_repo_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_github_inspect_repo_hardening", repo_path=repo)
    return ChatAgent(session)


def test_github_inspect_repo_tool_schema() -> None:
    assert GITHUB_INSPECT_REPO_TOOL["name"] == "github_inspect_repo"
    assert GITHUB_INSPECT_REPO_TOOL["input_schema"]["required"] == ["owner", "repo"]  # type: ignore[index]


def test_github_inspect_repo_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("github_inspect_repo") == 1


# ---------------------------------------------------------------------------
# Checked-safe: existing owner/repo/path validation (no fix needed, verified
# as a regression guard)
# ---------------------------------------------------------------------------


class TestExistingValidationConfirmedSafe:
    def test_direct_handler_rejects_slash_injection_via_owner(self) -> None:
        out = github_inspect_repo_handler({"owner": "evil.com/x#", "repo": "y"})
        assert "[ERROR]" in out

    def test_direct_handler_rejects_path_traversal(self) -> None:
        out = github_inspect_repo_handler(
            {"owner": "octocat", "repo": "Hello-World", "path": "../../etc"}
        )
        assert "[ERROR]" in out

    def test_make_chat_handlers_rejects_invalid_owner(self) -> None:
        handlers = make_chat_handlers(".")
        out = handlers["github_inspect_repo"]({"owner": "../evil", "repo": "x"})
        assert "[ERROR]" in out


# ---------------------------------------------------------------------------
# Finding — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    @pytest.mark.slow
    def test_chat_agent_dispatch_no_longer_unknown_tool(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool(
                "github_inspect_repo", {"owner": "octocat", "repo": "Hello-World"}
            )

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "octocat/Hello-World" in out

    def test_chat_agent_dispatch_still_rejects_injection(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool(
                "github_inspect_repo", {"owner": "evil.com/x#", "repo": "y"}
            )

        out = asyncio.run(_run())
        assert "[ERROR]" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real public repo, both real access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    @pytest.mark.slow
    def test_make_chat_handlers_inspects_real_repo(self) -> None:
        handlers = make_chat_handlers(".")
        out = handlers["github_inspect_repo"]({"owner": "octocat", "repo": "Hello-World"})
        assert "[ERROR]" not in out
        assert "octocat/Hello-World" in out

    @pytest.mark.slow
    def test_direct_handler_inspects_real_repo(self) -> None:
        out = github_inspect_repo_handler({"owner": "octocat", "repo": "Hello-World"})
        assert "octocat/Hello-World" in out
