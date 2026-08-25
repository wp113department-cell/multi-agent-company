"""check_license_compliance tool #103 — tool_enhance.md
productionization pass (2026-08-25).

One real, empirically-verified finding: "advertised but never
dispatched" — `chat_agent.py` had zero dispatch branch despite the
tool being fully advertised in `CHAT_TOOLS`, same class as tools
#4/#6/#22/#25/#33/#44/#45/#46/#48/#100. Every real interactive call
would have hit "Unknown tool".

No LLM-controlled input reaches this tool at all (empty schema), so
there is no injection/worktree-escape surface — the fix is purely
wiring a real dispatch to the existing, already-correct
`check_license_compliance_handler()` (real SPDX-based license
scanning of installed packages, per AUDIT_Q_BATCH11 §85).

All tests here run the real scanner against this repo's real installed
packages — nothing is mocked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.chat_agent import ChatAgent
from app.agents.tools import CHAT_TOOLS, make_chat_handlers
from app.models.chat import ChatSession
from app.tools.execution.check_license_compliance import (
    CHECK_LICENSE_COMPLIANCE_TOOL,
    check_license_compliance_handler,
)


def _agent(repo: Path) -> ChatAgent:
    session = ChatSession(
        session_id="td_check_license_compliance_hardening", repo_path=str(repo)
    )
    return ChatAgent(session)


def test_check_license_compliance_tool_schema() -> None:
    assert CHECK_LICENSE_COMPLIANCE_TOOL["name"] == "check_license_compliance"
    assert CHECK_LICENSE_COMPLIANCE_TOOL["input_schema"]["properties"] == {}  # type: ignore[index]
    assert CHECK_LICENSE_COMPLIANCE_TOOL["input_schema"]["required"] == []  # type: ignore[index]


def test_check_license_compliance_appears_exactly_once_in_chat_tools() -> None:
    names = [t["name"] for t in CHAT_TOOLS]
    assert names.count("check_license_compliance") == 1


# ---------------------------------------------------------------------------
# Finding — advertised but never dispatched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_dispatches_check_license_compliance(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("check_license_compliance", {})
    assert "Unknown tool" not in result


# ---------------------------------------------------------------------------
# Regression — real license scan works on both real access paths
# ---------------------------------------------------------------------------


def test_handler_returns_a_real_report() -> None:
    result = check_license_compliance_handler()
    assert isinstance(result, str)
    assert not result.startswith("[ERROR]")
    assert "license" in result.lower() or "copyleft" in result.lower()


@pytest.mark.asyncio
async def test_chat_agent_returns_a_real_report(tmp_path: Path) -> None:
    agent = _agent(tmp_path)
    result = await agent._execute_tool("check_license_compliance", {})
    assert not result.startswith("[ERROR]")
    assert "license" in result.lower() or "copyleft" in result.lower()


def test_make_chat_handlers_returns_a_real_report(tmp_path: Path) -> None:
    handlers = make_chat_handlers(str(tmp_path))
    result = handlers["check_license_compliance"]({})
    assert not result.startswith("[ERROR]")
    assert "license" in result.lower() or "copyleft" in result.lower()


def test_both_real_access_paths_agree() -> None:
    """The handler is a pure function of the installed environment (no
    LLM-controlled input) — both access paths must return identical
    results for the same environment snapshot."""
    direct = check_license_compliance_handler()
    handlers = make_chat_handlers(".")
    via_factory = handlers["check_license_compliance"]({})
    assert direct == via_factory
