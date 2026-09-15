"""list_processes tool #165 — tool_enhance.md productionization pass
(2026-09-15).

`filter` reaches only a pure in-memory Python string `in` containment
check against `ps aux`'s own output lines — never a subprocess or
shell command of any kind. No worktree-boundary-escape or
command-injection surface exists.

One real, empirically-verified finding — advertised in CHAT_TOOLS but
never dispatched by chat_agent.py. Proved live: a real call through
the real chat_agent.py dispatch returned "[ERROR] Unknown tool:
list_processes".

Fixed via a shared list_processes_handler(); a new chat_agent.py
dispatch branch delegates to it.

Note: assertions here deliberately avoid checking for the bare
substrings "ERROR"/"Unknown tool" against the FULL multi-line process
listing, since a real `ps aux` run naturally includes THIS test
process's own command line (which contains this docstring's own
source text) — a genuine false-positive risk discovered live while
hardening this exact tool. Assertions instead check the response's
own leading `[ERROR]`/`[ERROR] Unknown tool` prefix, or use a filter
value unlikely to self-reference.
"""

from __future__ import annotations

import asyncio

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.list_processes import (
    LIST_PROCESSES_TOOL,
    list_processes_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_list_processes_hardening", repo_path=repo)
    return ChatAgent(session)


def test_list_processes_tool_schema() -> None:
    assert LIST_PROCESSES_TOOL["name"] == "list_processes"
    assert LIST_PROCESSES_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_list_processes_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("list_processes") == 1


# ---------------------------------------------------------------------------
# Finding — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool("list_processes", {"filter": "init"})

        out = asyncio.run(_run())
        assert not out.startswith("[ERROR] Unknown tool")


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real live output, both real access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_no_filter(self) -> None:
        out = list_processes_handler({})
        assert not out.startswith("[ERROR]")
        assert "USER" in out

    def test_direct_handler_with_real_filter(self) -> None:
        # "init" (PID 1 on Linux) is always present and unlikely to
        # appear in this test's own command line.
        out = list_processes_handler({"filter": "init"})
        assert not out.startswith("[ERROR]")
        assert "USER" in out
        assert "init" in out.lower()

    def test_make_chat_handlers_returns_real_output(self) -> None:
        handlers = make_chat_handlers(".")
        out = handlers["list_processes"]({"filter": "init"})
        assert not out.startswith("[ERROR]")
        assert "USER" in out

    def test_chat_agent_dispatch_returns_real_output(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool("list_processes", {"filter": "init"})

        out = asyncio.run(_run())
        assert not out.startswith("[ERROR]")
        assert "USER" in out

    def test_result_capped_at_50_lines(self) -> None:
        out = list_processes_handler({})
        assert len(out.splitlines()) <= 50
