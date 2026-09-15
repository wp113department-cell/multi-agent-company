"""list_background_processes tool #162 — tool_enhance.md
productionization pass (2026-09-15).

No real bug found. The input schema is empty (no properties at all) —
no LLM-controlled input reaches this tool, so the worktree-boundary-
escape and injection classes established repeatedly this initiative do
not apply. Both real implementations (`list_background_processes_h` in
`make_chat_handlers` and `chat_agent.py`'s own dispatch — already
correctly wired, unusually for this initiative) already delegated to
the same, already-correct, already-shared
`app.fleet.process_manager.format_tracked()`. Consolidated the two
independently-hand-maintained duplicate one-liners into one shared
`list_background_processes_handler()`, per the mandatory modularization
rule for this initiative.
"""

from __future__ import annotations

import asyncio

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.list_background_processes import (
    LIST_BACKGROUND_PROCESSES_TOOL,
    list_background_processes_handler,
)


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(
        session_id="td_list_background_processes_hardening", repo_path=repo
    )
    return ChatAgent(session)


def test_list_background_processes_tool_schema() -> None:
    assert LIST_BACKGROUND_PROCESSES_TOOL["name"] == "list_background_processes"
    assert LIST_BACKGROUND_PROCESSES_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_list_background_processes_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("list_background_processes") == 1


class TestDirectHandler:
    def test_empty_registry(self) -> None:
        out = list_background_processes_handler({})
        assert "no tracked background processes" in out


class TestBothRealAccessPathsWithARealProcess:
    def test_make_chat_handlers_reports_a_real_running_process(self) -> None:
        handlers = make_chat_handlers(".")
        run_bg_out = handlers["run_background"](
            {"command": "sleep 3", "expected_seconds": 10}
        )
        assert "Started background process" in run_bg_out

        out = handlers["list_background_processes"]({})
        assert "sleep 3" in out
        assert "PID" in out

    def test_chat_agent_dispatch_reports_a_real_process(self) -> None:
        agent = _agent(".")

        async def _run() -> tuple[str, str]:
            run_bg_out = await agent._execute_tool(
                "run_background", {"command": "sleep 2", "expected_seconds": 10}
            )
            list_out = await agent._execute_tool("list_background_processes", {})
            return run_bg_out, list_out

        run_bg_out, list_out = asyncio.run(_run())
        assert "Started background process" in run_bg_out
        assert "Unknown tool" not in list_out
        assert "sleep 2" in list_out
