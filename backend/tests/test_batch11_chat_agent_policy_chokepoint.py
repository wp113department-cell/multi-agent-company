"""AUDIT_Q_BATCH11 §85 "All agents automatically follow policy (structural
guarantee)" — proves ChatAgent._execute_tool_node now has a real central
policy chokepoint (reusing base_graph.py's manifest-driven _policy_check),
not just per-branch inline checks scattered across its ~150 `if tool_name
==` branches.

The structural proof: a policy-denied call must short-circuit BEFORE
self._execute_tool() (the function containing all those per-branch
handlers) is ever invoked — i.e. the guarantee holds even for a
hypothetical future branch that forgot its own inline check, not just for
the ones that happen to remember today.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.chat_agent import ChatAgent


def _make_agent() -> ChatAgent:
    agent = ChatAgent.__new__(ChatAgent)  # bypass __init__
    agent.session = MagicMock()
    agent.session.session_id = "batch11_policy_chokepoint"
    agent.session.push = AsyncMock()
    agent.session.history = []
    agent._current_tool_use_id = ""
    return agent


def _tool_result_output(agent: ChatAgent) -> str:
    """The tool_result event is always pushed (success or denial) — pull
    its "output" field, the most direct real signal of what the tool call
    actually resolved to."""
    for call in agent.session.push.call_args_list:
        event = call.args[0]
        if event.get("type") == "tool_result":
            return str(event.get("output", ""))
    raise AssertionError("no tool_result event was pushed")


@pytest.mark.asyncio
async def test_protected_path_write_short_circuits_before_execute_tool() -> None:
    agent = _make_agent()
    with patch.object(
        agent, "_execute_tool", new=AsyncMock(return_value="should never run")
    ) as mock_execute:
        await agent._execute_tool_node(
            {
                "pending_tool_uses": [
                    {
                        "id": "toolu_1",
                        "name": "write_file",
                        "input": {"path": ".env", "content": "SECRET=1"},
                    }
                ],
                "verification": {"read": True},
            }
        )
    mock_execute.assert_not_called()
    assert "[POLICY DENIED]" in _tool_result_output(agent)


@pytest.mark.asyncio
async def test_dangerous_command_short_circuits_before_execute_tool() -> None:
    agent = _make_agent()
    with patch.object(
        agent, "_execute_tool", new=AsyncMock(return_value="should never run")
    ) as mock_execute:
        await agent._execute_tool_node(
            {
                "pending_tool_uses": [
                    {
                        "id": "toolu_2",
                        "name": "docker_exec",
                        "input": {"container": "web", "command": "rm -rf /"},
                    }
                ],
                "verification": {"read": True},
            }
        )
    mock_execute.assert_not_called()
    assert "[POLICY DENIED]" in _tool_result_output(agent)


@pytest.mark.asyncio
async def test_safe_call_still_reaches_execute_tool() -> None:
    """The chokepoint must not become a blanket deny — a legitimate call
    still reaches the real handler."""
    agent = _make_agent()
    with patch.object(
        agent, "_execute_tool", new=AsyncMock(return_value="Written: src/main.py")
    ) as mock_execute:
        await agent._execute_tool_node(
            {
                "pending_tool_uses": [
                    {
                        "id": "toolu_3",
                        "name": "write_file",
                        "input": {"path": "src/main.py", "content": "x = 1"},
                    }
                ],
                "verification": {"read": True},
            }
        )
    mock_execute.assert_called_once_with(
        "write_file", {"path": "src/main.py", "content": "x = 1"}
    )
    assert "Written: src/main.py" in _tool_result_output(agent)
