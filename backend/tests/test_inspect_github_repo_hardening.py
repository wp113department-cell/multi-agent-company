"""inspect_github_repo tool #156 — tool_enhance.md productionization
pass (2026-09-14).

Audited thoroughly; NO real bug found. There was already only one
real implementation (`make_chat_handlers()` and `chat_agent.py` both
called the exact same module-level `inspect_github_repo` function
object, confirmed via grep — no duplication or drift risk, unlike
most tools this initiative).

Checked and CONFIRMED already safe:
- owner/repo validated against ^[A-Za-z0-9._-]+$.
- path traversal (a plain "..") rejected before any request; proved
  live against the REAL GitHub API that URL-encoded and
  double-encoded traversal attempts are also harmless (the real
  GitHub contents API returns a plain 404 for both, not a bypass).
- No shell-injection risk (list-args subprocess only).
- Already correctly dispatched by chat_agent.py before this turn.

Modularization only — see app/tools/integrations/inspect_github_repo.py.
"""

from __future__ import annotations

import asyncio

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, inspect_github_repo, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.integrations.inspect_github_repo import (
    INSPECT_GITHUB_REPO_TOOL,
    inspect_github_repo_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_inspect_github_repo_hardening", repo_path=repo)
    return ChatAgent(session)


def test_inspect_github_repo_tool_schema() -> None:
    assert INSPECT_GITHUB_REPO_TOOL["name"] == "inspect_github_repo"
    assert INSPECT_GITHUB_REPO_TOOL["input_schema"]["required"] == ["owner", "repo"]  # type: ignore[index]


def test_inspect_github_repo_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("inspect_github_repo") == 1


def test_old_module_level_wrapper_still_importable_and_delegates() -> None:
    """Backward compatibility: existing tests/callers import
    inspect_github_repo directly from app.agents.tools."""
    out = inspect_github_repo({"owner": "", "repo": "x"})
    assert "[ERROR]" in out


# ---------------------------------------------------------------------------
# Checked-safe: path-traversal encoding bypass attempts against the real
# GitHub API (no fix needed, verified as a regression guard)
# ---------------------------------------------------------------------------


class TestPathTraversalConfirmedSafe:
    def test_plain_traversal_rejected_before_any_request(self) -> None:
        out = inspect_github_repo_handler(
            {"owner": "octocat", "repo": "Hello-World", "action": "read_file", "path": "../user"}
        )
        assert out == "[ERROR] path may not contain '..'"

    def test_url_encoded_traversal_harmless_against_real_api(self) -> None:
        out = inspect_github_repo_handler(
            {
                "owner": "octocat",
                "repo": "Hello-World",
                "action": "read_file",
                "path": "..%2f..%2fuser",
            }
        )
        assert "[ERROR]" in out
        assert "404" in out or "Not Found" in out

    def test_double_encoded_traversal_harmless_against_real_api(self) -> None:
        out = inspect_github_repo_handler(
            {
                "owner": "octocat",
                "repo": "Hello-World",
                "action": "read_file",
                "path": "..%252f..%252fuser",
            }
        )
        assert "[ERROR]" in out
        assert "404" in out or "Not Found" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real public repo, both real access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_real_info(self) -> None:
        out = inspect_github_repo_handler({"owner": "octocat", "repo": "Hello-World"})
        assert "Hello-World" in out

    def test_make_chat_handlers_real_info(self) -> None:
        handlers = make_chat_handlers(".")
        out = handlers["inspect_github_repo"]({"owner": "octocat", "repo": "Hello-World"})
        assert "Hello-World" in out

    def test_chat_agent_dispatch_real_info(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool(
                "inspect_github_repo", {"owner": "octocat", "repo": "Hello-World"}
            )

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "Hello-World" in out
