"""list_open_ports tool #164 — tool_enhance.md productionization
pass (2026-09-15).

The input schema is empty (no properties at all) — no LLM-controlled
input reaches this tool. Both commands (`ss -tlnp`, falling back to
`netstat -tlnp`) are fixed literal argv lists run via list-args
`subprocess.run()`, never `shell=True` — no worktree-boundary-escape
or command-injection surface exists.

One real, empirically-verified finding — advertised in CHAT_TOOLS but
never dispatched by chat_agent.py. Proved live: a real call through
the real chat_agent.py dispatch returned "[ERROR] Unknown tool:
list_open_ports".

Fixed via a shared list_open_ports_handler(); a new chat_agent.py
dispatch branch delegates to it.
"""

from __future__ import annotations

import asyncio

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.list_open_ports import (
    LIST_OPEN_PORTS_TOOL,
    list_open_ports_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_list_open_ports_hardening", repo_path=repo)
    return ChatAgent(session)


def test_list_open_ports_tool_schema() -> None:
    assert LIST_OPEN_PORTS_TOOL["name"] == "list_open_ports"
    assert LIST_OPEN_PORTS_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_list_open_ports_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("list_open_ports") == 1


# ---------------------------------------------------------------------------
# Finding — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool("list_open_ports", {})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real live output, both real access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_returns_real_output(self) -> None:
        out = list_open_ports_handler()
        assert "[ERROR]" not in out
        assert out != ""

    def test_make_chat_handlers_returns_real_output(self) -> None:
        handlers = make_chat_handlers(".")
        out = handlers["list_open_ports"]({})
        assert "[ERROR]" not in out

    def test_chat_agent_dispatch_returns_real_output(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool("list_open_ports", {})

        out = asyncio.run(_run())
        assert "[ERROR]" not in out
        assert out != ""
