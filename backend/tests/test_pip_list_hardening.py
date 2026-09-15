"""pip_list tool #172 — tool_enhance.md productionization pass
(2026-09-15).

Audit: `filter` was checked for the shell/CLI-flag-collision class
established repeatedly this initiative (e.g. tools #5/#32/#148/#149/
#158) — CONFIRMED NOT VULNERABLE. `filter` never reaches a subprocess
or shell at all: it is a pure in-memory Python substring check
applied to the already-captured stdout of a fixed, list-args
`subprocess.run` call with zero LLM-controlled arguments. Proved
live: `filter="-n"` behaves as an ordinary substring filter, no
different from any other value.

One real finding: advertised in CHAT_TOOLS but never dispatched by
chat_agent.py. Fixed via a new chat_agent.py dispatch branch
delegating to the shared `pip_list_handler()`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.pip_list import PIP_LIST_TOOL, pip_list_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_pip_list_hardening", repo_path=repo)
    return ChatAgent(session)


def test_pip_list_tool_schema() -> None:
    assert PIP_LIST_TOOL["name"] == "pip_list"
    assert PIP_LIST_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_pip_list_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("pip_list") == 1


# ---------------------------------------------------------------------------
# Audit — confirmed no flag-collision / injection surface (documented, not
# a vulnerability since `filter` never reaches a subprocess/shell)
# ---------------------------------------------------------------------------


class TestFilterNoInjectionSurface:
    def test_flag_shaped_filter_behaves_as_ordinary_substring(self) -> None:
        out = pip_list_handler({"filter": "-n"})
        assert "[ERROR]" not in out
        assert "Package" in out

    def test_filter_with_shell_metacharacters_is_inert(self) -> None:
        out = pip_list_handler({"filter": "; touch /tmp/PWNED_pip_list_test ;"})
        assert "[ERROR]" not in out
        assert "Package" in out
        import os

        assert not os.path.exists("/tmp/PWNED_pip_list_test")


# ---------------------------------------------------------------------------
# Finding — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self, tmp_path: Path) -> None:
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool("pip_list", {})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        assert "Package" in out

    def test_chat_agent_dispatch_respects_filter(self, tmp_path: Path) -> None:
        agent = _agent(str(tmp_path))

        async def _run() -> str:
            return await agent._execute_tool("pip_list", {"filter": "pytest"})

        out = asyncio.run(_run())
        assert "pytest" in out.lower()


# ---------------------------------------------------------------------------
# Legitimate-usage regression — real installed packages, both access paths
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_lists_real_packages(self) -> None:
        out = pip_list_handler({})
        assert "Package" in out
        assert "pytest" in out.lower()

    def test_make_chat_handlers_lists_real_packages(self, tmp_path: Path) -> None:
        handlers = make_chat_handlers(str(tmp_path))
        out = handlers["pip_list"]({})
        assert "Package" in out

    def test_filter_narrows_results(self) -> None:
        out = pip_list_handler({"filter": "pytest"})
        lines = [ln for ln in out.splitlines() if ln and not ln.startswith("Package") and not ln.startswith("---")]
        assert all("pytest" in ln.lower() for ln in lines)
