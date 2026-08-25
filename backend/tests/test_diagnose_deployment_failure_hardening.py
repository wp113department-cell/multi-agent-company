"""diagnose_deployment_failure tool #106 — tool_enhance.md
productionization pass (2026-08-25).

Two real, empirically-verified findings:

1. The most severe: a genuine, direct shell-injection on
   `chat_agent.py`'s dispatch — `container` was interpolated
   completely unquoted into two separate `shell=True` commands.
   Proved live with a real file created via injected command.
2. A flag-collision on `container` (bare positional, no `--`
   separator) across all three implementations, plus an uncaught
   `ValueError` on a non-numeric `lines`.

Fixed via a shared `gather_deployment_diagnostics()` — list-args
subprocess calls only, plus real `container`/`lines` validators. The
LLM diagnosis step itself (`_llm_diagnose_deployment_failure`) is
unchanged — no bug found there, all tests mock it, matching the
existing test suite's own established convention.

All tests here use real docker subprocess calls (docker itself is
never mocked) except the LLM diagnosis step, which every test mocks
(matching `test_audit_q_batch10_deployment_external_git_docs.py`'s own
convention, since it makes a real network call otherwise).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import (
    CHAT_TOOLS,
    make_chat_handlers,
    make_docker_agent_handlers,
)
from app.models.chat import ChatSession
from app.tools.execution.diagnose_deployment_failure import (
    DIAGNOSE_DEPLOYMENT_FAILURE_TOOL,
    gather_deployment_diagnostics,
)


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(
        session_id="td_diagnose_deployment_failure_hardening", repo_path=str(repo)
    )
    return ChatAgent(session)


def test_diagnose_deployment_failure_tool_schema() -> None:
    assert DIAGNOSE_DEPLOYMENT_FAILURE_TOOL["name"] == "diagnose_deployment_failure"
    assert DIAGNOSE_DEPLOYMENT_FAILURE_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_diagnose_deployment_failure_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("diagnose_deployment_failure") == 1


# ---------------------------------------------------------------------------
# Finding #1 — genuine shell injection (chat_agent.py dispatch only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_rejects_shell_injection_via_container(tmp_path: Path) -> None:
    marker = tmp_path.parent / "diagnose_deployment_hardening_PWNED_marker.txt"
    if marker.exists():
        marker.unlink()
    agent = _agent(tmp_path)
    payload = f"; touch {marker}; echo x"
    with patch(
        "app.agents.chat_agent._llm_diagnose_deployment_failure",
        return_value="(mocked diagnosis)",
    ):
        result = await agent._execute_tool(
            "diagnose_deployment_failure", {"container": payload}
        )
    assert not marker.exists(), "shell injection must not execute a real command"
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Finding #2 — flag-collision + uncaught ValueError
# ---------------------------------------------------------------------------


def test_gather_rejects_flag_shaped_container() -> None:
    result = gather_deployment_diagnostics({"container": "-f"})
    assert result.startswith("[ERROR]")
    assert "flag" in result


def test_gather_rejects_non_numeric_lines() -> None:
    result = gather_deployment_diagnostics({"lines": "not-a-number"})
    assert result.startswith("[ERROR]")
    assert "lines" in result


@pytest.mark.asyncio
async def test_chat_agent_rejects_flag_shaped_container(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "diagnose_deployment_failure", {"container": "--privileged"}
    )
    assert "[ERROR]" in result
    assert "flag" in result


@pytest.mark.asyncio
async def test_chat_agent_rejects_non_numeric_lines(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool(
        "diagnose_deployment_failure", {"lines": "abc"}
    )
    assert "[ERROR]" in result
    assert "lines" in result


@pytest.mark.parametrize(
    "factory_name,factory",
    [
        ("make_chat_handlers", make_chat_handlers),
        ("docker_agent", make_docker_agent_handlers),
    ],
)
def test_both_factories_reject_flag_shaped_container(
    tmp_path: Path, factory_name: str, factory
) -> None:
    handlers = factory(str(tmp_path))
    result = handlers["diagnose_deployment_failure"]({"container": "-f"})
    assert "[ERROR]" in result, f"{factory_name} did not reject the flag-shaped container"


# ---------------------------------------------------------------------------
# Regression — legitimate usage across all three real access paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_gathers_real_docker_state(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    with patch(
        "app.agents.chat_agent._llm_diagnose_deployment_failure",
        return_value="(mocked diagnosis)",
    ):
        result = await agent._execute_tool("diagnose_deployment_failure", {})
    assert "docker ps -a" in result
    assert "=== Diagnosis ===" in result
    assert "(mocked diagnosis)" in result


@pytest.mark.parametrize(
    "factory",
    [make_chat_handlers, make_docker_agent_handlers],
)
def test_both_factories_gather_real_docker_state(tmp_path: Path, factory) -> None:
    handlers = factory(str(tmp_path))
    with patch(
        "app.agents.tools._llm_diagnose_deployment_failure",
        return_value="(mocked diagnosis)",
    ):
        result = handlers["diagnose_deployment_failure"]({})
    assert "docker ps -a" in result
    assert "(mocked diagnosis)" in result
