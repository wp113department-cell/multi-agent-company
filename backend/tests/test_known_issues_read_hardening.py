"""known_issues_read tool #160 — tool_enhance.md productionization
pass (2026-09-15).

The input schema is empty (no properties at all), and the file path
this tool reads is derived deterministically from `repo_path` into a
fixed internal memory directory — never from any LLM-controlled input
field. No worktree-boundary-escape or injection surface exists.

One real, empirically-verified finding — advertised in CHAT_TOOLS but
never dispatched by chat_agent.py. Proved live: a real call through
the real chat_agent.py dispatch returned "[ERROR] Unknown tool:
known_issues_read".

Fixed via a shared known_issues_read_handler(); a new chat_agent.py
dispatch branch delegates to it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.agents.known_issues_read import (
    KNOWN_ISSUES_READ_TOOL,
    known_issues_path,
    known_issues_read_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_known_issues_read_hardening", repo_path=repo)
    return ChatAgent(session)


def test_known_issues_read_tool_schema() -> None:
    assert KNOWN_ISSUES_READ_TOOL["name"] == "known_issues_read"
    assert KNOWN_ISSUES_READ_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_known_issues_read_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("known_issues_read") == 1


def _cleanup(repo: str) -> None:
    path = known_issues_path(repo)
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# Finding — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self) -> None:
        repo = "/tmp/td_kir_hardening_repo_a"
        _cleanup(repo)
        agent = _agent(repo)

        async def _run() -> str:
            return await agent._execute_tool("known_issues_read", {})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "no known issues" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real file content, both real access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_no_file_yet(self) -> None:
        repo = "/tmp/td_kir_hardening_repo_b"
        _cleanup(repo)
        out = known_issues_read_handler(repo)
        assert out == "(no known issues file yet)"

    def test_direct_handler_reads_real_content(self) -> None:
        repo = "/tmp/td_kir_hardening_repo_c"
        path = known_issues_path(repo)
        path.parent.mkdir(exist_ok=True)
        path.write_text("## [HIGH] 2026-01-01\nReal known issue text\n")
        try:
            out = known_issues_read_handler(repo)
            assert "Real known issue text" in out
        finally:
            path.unlink()

    def test_make_chat_handlers_reads_real_content(self) -> None:
        repo = "/tmp/td_kir_hardening_repo_d"
        path = known_issues_path(repo)
        path.parent.mkdir(exist_ok=True)
        path.write_text("## [LOW] 2026-01-02\nAnother issue\n")
        try:
            handlers = make_chat_handlers(repo)
            out = handlers["known_issues_read"]({})
            assert "Another issue" in out
        finally:
            path.unlink()

    def test_chat_agent_dispatch_reads_real_content(self) -> None:
        repo = "/tmp/td_kir_hardening_repo_e"
        path = known_issues_path(repo)
        path.parent.mkdir(exist_ok=True)
        path.write_text("## [MEDIUM] 2026-01-03\nYet another issue\n")
        agent = _agent(repo)

        async def _run() -> str:
            return await agent._execute_tool("known_issues_read", {})

        try:
            out = asyncio.run(_run())
            assert "Yet another issue" in out
        finally:
            path.unlink()

    def test_known_issues_path_matches_write_handler_derivation(self) -> None:
        """known_issues_path() must derive the exact same file as
        known_issues_write_h's own _mem_issues_path so read/write see
        the same file — verified via the real md5-slug formula."""
        import hashlib

        repo = "/tmp/td_kir_hardening_repo_f"
        expected_slug = hashlib.md5(repo.encode()).hexdigest()[:8]
        path = known_issues_path(repo)
        assert path.name == f"{expected_slug}_known_issues.md"
        assert path.parent == Path(__file__).parent.parent / "app" / "memory"
