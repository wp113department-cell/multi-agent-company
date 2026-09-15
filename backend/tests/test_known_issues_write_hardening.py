"""known_issues_write tool #161 — tool_enhance.md productionization
pass (2026-09-15).

`issue`/`severity` are free-text fields appended into a markdown log
file, but the destination path itself (shared with sibling tool
#160's `known_issues_read`) is derived deterministically from
`repo_path` alone, never from either input field — no
worktree-boundary-escape or path-injection surface exists. They reach
`embed_bug_sync()`, which uses SQLAlchemy ORM parameter binding, not
raw string-formatted SQL — no injection surface there either.

One real, empirically-verified finding — advertised in CHAT_TOOLS but
never dispatched by chat_agent.py. Proved live: a real call through
the real chat_agent.py dispatch returned "[ERROR] Unknown tool:
known_issues_write".

Fixed via a shared known_issues_write_handler(); a new chat_agent.py
dispatch branch delegates to it. The original's cross-platform
advisory file lock (msvcrt on Windows, fcntl elsewhere) is preserved
unchanged.
"""

from __future__ import annotations

import asyncio

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.agents.known_issues_read import known_issues_path
from app.tools.agents.known_issues_write import (
    KNOWN_ISSUES_WRITE_TOOL,
    known_issues_write_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_known_issues_write_hardening", repo_path=repo)
    return ChatAgent(session)


def _cleanup(repo: str) -> None:
    path = known_issues_path(repo)
    if path.exists():
        path.unlink()


def test_known_issues_write_tool_schema() -> None:
    assert KNOWN_ISSUES_WRITE_TOOL["name"] == "known_issues_write"
    assert KNOWN_ISSUES_WRITE_TOOL["input_schema"]["required"] == ["issue", "severity"]  # type: ignore[index]


def test_known_issues_write_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("known_issues_write") == 1


# ---------------------------------------------------------------------------
# Finding — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self) -> None:
        repo = "/tmp/td_kiw_hardening_repo_a"
        _cleanup(repo)
        agent = _agent(repo)

        async def _run() -> str:
            return await agent._execute_tool(
                "known_issues_write", {"issue": "chat dispatch issue", "severity": "low"}
            )

        try:
            out = asyncio.run(_run())
            assert "Unknown tool" not in out
            assert "Known issue appended" in out
        finally:
            _cleanup(repo)


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real appends, both real access paths, and
# a round-trip read-back proving the write actually persisted
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_appends_and_is_readable(self) -> None:
        repo = "/tmp/td_kiw_hardening_repo_b"
        _cleanup(repo)
        try:
            out = known_issues_write_handler(
                repo, {"issue": "real direct issue", "severity": "critical"}
            )
            assert "Known issue appended (severity: CRITICAL)" in out
            path = known_issues_path(repo)
            content = path.read_text(encoding="utf-8")
            assert "real direct issue" in content
            assert "[CRITICAL]" in content
        finally:
            _cleanup(repo)

    def test_make_chat_handlers_appends_and_is_readable(self) -> None:
        repo = "/tmp/td_kiw_hardening_repo_c"
        _cleanup(repo)
        try:
            handlers = make_chat_handlers(repo)
            out = handlers["known_issues_write"](
                {"issue": "make_chat_handlers issue", "severity": "medium"}
            )
            assert "Known issue appended" in out
            read_out = handlers["known_issues_read"]({})
            assert "make_chat_handlers issue" in read_out
        finally:
            _cleanup(repo)

    def test_chat_agent_dispatch_appends_and_is_readable(self) -> None:
        repo = "/tmp/td_kiw_hardening_repo_d"
        _cleanup(repo)
        agent = _agent(repo)

        async def _run() -> tuple[str, str]:
            write_out = await agent._execute_tool(
                "known_issues_write", {"issue": "chat issue", "severity": "high"}
            )
            read_out = await agent._execute_tool("known_issues_read", {})
            return write_out, read_out

        try:
            write_out, read_out = asyncio.run(_run())
            assert "Known issue appended" in write_out
            assert "chat issue" in read_out
        finally:
            _cleanup(repo)

    def test_multiple_writes_append_rather_than_overwrite(self) -> None:
        repo = "/tmp/td_kiw_hardening_repo_e"
        _cleanup(repo)
        try:
            known_issues_write_handler(repo, {"issue": "first issue", "severity": "low"})
            known_issues_write_handler(repo, {"issue": "second issue", "severity": "low"})
            path = known_issues_path(repo)
            content = path.read_text(encoding="utf-8")
            assert "first issue" in content
            assert "second issue" in content
        finally:
            _cleanup(repo)

    def test_default_severity_is_medium(self) -> None:
        repo = "/tmp/td_kiw_hardening_repo_f"
        _cleanup(repo)
        try:
            out = known_issues_write_handler(repo, {"issue": "no severity given"})
            assert "MEDIUM" in out
        finally:
            _cleanup(repo)
