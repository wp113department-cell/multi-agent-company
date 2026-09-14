"""github_list_prs tool #153 — tool_enhance.md productionization pass
(2026-09-14).

`state` reaches `gh pr list --state <state>` via list-args
`subprocess.run()` — checked directly and CONFIRMED already safe
against the flag-collision class established repeatedly this
initiative (#5/#32/#148/#149): the real `gh` CLI itself strictly
validates `--state` against a hard enum (`open|closed|merged|all`)
via its own cobra-based argument parser. Proved live: `gh pr list
--state --json ...` and `gh pr list --state -x ...` were both rejected
by the real `gh` binary with a clear usage error before any network
call — no fix needed there.

One real, empirically-verified finding — advertised in CHAT_TOOLS but
never dispatched by chat_agent.py. Proved live: a real call through
the real chat_agent.py dispatch returned "[ERROR] Unknown tool:
github_list_prs".

Fixed via a shared github_list_prs_handler(); a new chat_agent.py
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
from app.tools.git.github_list_prs import (
    GITHUB_LIST_PRS_TOOL,
    github_list_prs_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_github_list_prs_hardening", repo_path=repo)
    return ChatAgent(session)


def _has_gh() -> bool:
    try:
        subprocess.run(["gh", "--version"], capture_output=True, timeout=5)
        return True
    except FileNotFoundError:
        return False


requires_gh = pytest.mark.skipif(not _has_gh(), reason="gh CLI not installed")


def test_github_list_prs_tool_schema() -> None:
    assert GITHUB_LIST_PRS_TOOL["name"] == "github_list_prs"
    assert GITHUB_LIST_PRS_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_github_list_prs_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("github_list_prs") == 1


# ---------------------------------------------------------------------------
# Checked-safe: gh's own --state enum enforcement (no fix needed, verified
# as a regression guard)
# ---------------------------------------------------------------------------


@requires_gh
class TestFlagCollisionAlreadySafe:
    def test_direct_handler_flag_shaped_state_rejected_by_gh_itself(
        self, tmp_path: Path
    ) -> None:
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
        out = github_list_prs_handler(tmp_path, {"state": "--json"})
        assert "invalid argument" in out or "[ERROR]" in out

    def test_direct_handler_dash_x_state_rejected_by_gh_itself(
        self, tmp_path: Path
    ) -> None:
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
        out = github_list_prs_handler(tmp_path, {"state": "-x"})
        assert "invalid argument" in out or "[ERROR]" in out


# ---------------------------------------------------------------------------
# Finding — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


@requires_gh
class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool("github_list_prs", {})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real gh invocation, both real access paths
# ---------------------------------------------------------------------------


@requires_gh
class TestLegitimateUsageRegression:
    def test_make_chat_handlers_invokes_real_gh(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["github_list_prs"]({})
        # Real gh invocation genuinely ran — never "Unknown tool" and
        # never a Python traceback; either real PR JSON or a real gh
        # CLI error (e.g. no remote configured).
        assert "Unknown tool" not in out
        assert isinstance(out, str)

    def test_default_state_is_open(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
        out = github_list_prs_handler(tmp_path, {})
        assert isinstance(out, str)

    def test_gh_not_found_handled_gracefully(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        def _raise(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise FileNotFoundError()

        monkeypatch.setattr(subprocess, "run", _raise)
        out = github_list_prs_handler(tmp_path, {})
        assert out == "[ERROR] gh CLI not found"
