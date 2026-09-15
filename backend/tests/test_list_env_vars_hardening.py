"""list_env_vars tool #163 — tool_enhance.md productionization pass
(2026-09-15).

The input schema is empty (no properties at all) — no LLM-controlled
input reaches this tool. Checked and CONFIRMED already safe on its own
documented safety contract ("List all environment variable NAMES (not
values)"): proved live with a real, deliberately secret-shaped
environment variable — its name appeared in the result, its value
never did.

One real, empirically-verified finding — advertised in CHAT_TOOLS but
never dispatched by chat_agent.py. Proved live: a real call through
the real chat_agent.py dispatch returned "[ERROR] Unknown tool:
list_env_vars".

Fixed via a shared list_env_vars_handler(); a new chat_agent.py
dispatch branch delegates to it.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.list_env_vars import LIST_ENV_VARS_TOOL, list_env_vars_handler


def _agent(repo: str) -> ChatAgent:
    session = ChatSession(session_id="td_list_env_vars_hardening", repo_path=repo)
    return ChatAgent(session)


def test_list_env_vars_tool_schema() -> None:
    assert LIST_ENV_VARS_TOOL["name"] == "list_env_vars"
    assert LIST_ENV_VARS_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_list_env_vars_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("list_env_vars") == 1


@pytest.fixture
def secret_env_var(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    name = "TD_LIST_ENV_VARS_SECRET_VAR"
    value = "do_not_leak_this_value_xyz123"
    monkeypatch.setenv(name, value)
    return name, value


# ---------------------------------------------------------------------------
# Checked-safe: names-only, never values (no fix needed, verified as a
# regression guard)
# ---------------------------------------------------------------------------


class TestNamesOnlyContractConfirmedSafe:
    def test_direct_handler_lists_name_never_value(
        self, secret_env_var: tuple[str, str]
    ) -> None:
        name, value = secret_env_var
        out = list_env_vars_handler()
        assert name in out
        assert value not in out

    def test_make_chat_handlers_lists_name_never_value(
        self, secret_env_var: tuple[str, str]
    ) -> None:
        name, value = secret_env_var
        handlers = make_chat_handlers(".")
        out = handlers["list_env_vars"]({})
        assert name in out
        assert value not in out

    def test_chat_agent_dispatch_lists_name_never_value(
        self, secret_env_var: tuple[str, str]
    ) -> None:
        name, value = secret_env_var
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool("list_env_vars", {})

        out = asyncio.run(_run())
        assert name in out
        assert value not in out


# ---------------------------------------------------------------------------
# Finding — dispatch is now genuinely reachable from interactive chat
# ---------------------------------------------------------------------------


class TestChatDispatchReachable:
    def test_chat_agent_dispatch_no_longer_unknown_tool(self) -> None:
        agent = _agent(".")

        async def _run() -> str:
            return await agent._execute_tool("list_env_vars", {})

        out = asyncio.run(_run())
        assert "Unknown tool" not in out
        # A real, always-present env var on this system (PATH) should
        # be listed, confirming genuine os.environ access happened.
        assert "PATH" in out


# ---------------------------------------------------------------------------
# Legitimate-usage regression
# ---------------------------------------------------------------------------


class TestLegitimateUsageRegression:
    def test_direct_handler_returns_sorted_real_names(self) -> None:
        out = list_env_vars_handler()
        lines = out.splitlines()
        assert lines == sorted(lines)
        assert set(lines) == set(os.environ.keys())
