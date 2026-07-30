"""Gap-closure Day 15 (Stage 1.2, answers.md) — proves `expected_verification`
is now a REAL blocking check, not tracked-but-unenforced metadata.
`VerificationConfig.blocking_until` ({tool_name: verification_key}) is new:
before this, nothing in `execute_tools`/`_make_execute_tools_node` (grepped
before writing this) ever refused a tool call because a verification flag
was unset — a tool's `AGENT_CONTRACT["expected_verification"]` was pure
documentation, read by nobody at runtime.

Reuses test_phase37_quality_gate.py's own established pattern for calling
`_make_execute_tools_node` directly (no LLM, no graph compile needed to
test the tool-execution node in isolation).
"""

from __future__ import annotations

from typing import Any

from app.agents.base_graph import (
    AgentRunState,
    VerificationConfig,
    _make_execute_tools_node,
)
from app.agents.dependency_security_agent import _CFG as DEP_SEC_CFG

_BASH_TOOL = {
    "name": "bash",
    "description": "Run a command",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}
_READ_FILE_TOOL = {
    "name": "read_file",
    "description": "Read a file",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}


def _tool_use_state(
    tool_name: str, tool_input: dict[str, Any], verification: dict[str, Any]
) -> AgentRunState:
    return {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu1",
                        "name": tool_name,
                        "input": tool_input,
                    }
                ],
            }
        ],
        "verification": verification,
        "result": {},
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
        "turns": 1,
        "confidence": 1.0,
        "critique_result": {},
    }


def test_blocking_until_defaults_to_empty_zero_behavior_change() -> None:
    """The default VerificationConfig() has an empty blocking_until — every
    existing agent that doesn't opt in keeps its exact current behavior."""
    cfg = VerificationConfig()
    assert cfg.blocking_until == {}


def test_tool_is_refused_when_its_required_flag_is_unset() -> None:
    handler_called = {"value": False}

    def bash_handler(inp: dict[str, Any]) -> str:
        handler_called["value"] = True
        return "should never run"

    cfg = VerificationConfig(blocking_until={"bash": "read"})
    node = _make_execute_tools_node(
        tool_handlers={"bash": bash_handler},
        verification_cfg=cfg,
        human_approval_required=False,
        tools=[_BASH_TOOL],
    )

    result = node(
        _tool_use_state("bash", {"command": "echo hi"}, verification={"read": False})
    )

    tool_result_content = result["messages"][-1]["content"][0]["content"]
    assert tool_result_content.startswith("[POLICY DENIED]")
    assert "read" in tool_result_content
    assert handler_called["value"] is False, "the real handler must never run"


def test_tool_runs_normally_once_its_required_flag_is_set() -> None:
    handler_called = {"value": False}

    def bash_handler(inp: dict[str, Any]) -> str:
        handler_called["value"] = True
        return "real output"

    cfg = VerificationConfig(blocking_until={"bash": "read"})
    node = _make_execute_tools_node(
        tool_handlers={"bash": bash_handler},
        verification_cfg=cfg,
        human_approval_required=False,
        tools=[_BASH_TOOL],
    )

    result = node(
        _tool_use_state("bash", {"command": "echo hi"}, verification={"read": True})
    )

    tool_result_content = result["messages"][-1]["content"][0]["content"]
    assert tool_result_content == "real output"
    assert handler_called["value"] is True


def test_a_tool_with_no_blocking_entry_is_never_gated() -> None:
    """Only tools explicitly named in blocking_until are affected — a tool
    absent from the mapping runs regardless of any verification state."""
    cfg = VerificationConfig(blocking_until={"bash": "read"})
    node = _make_execute_tools_node(
        tool_handlers={"read_file": lambda inp: "file contents"},
        verification_cfg=cfg,
        human_approval_required=False,
        tools=[_READ_FILE_TOOL],
    )

    result = node(
        _tool_use_state("read_file", {"path": "a.py"}, verification={"read": False})
    )

    # read_file's real output is wrapped in Phase 6.3's <untrusted_external_data>
    # delimiters (unrelated to this test) — check containment, not equality.
    tool_result_content = result["messages"][-1]["content"][0]["content"]
    assert "file contents" in tool_result_content
    assert not tool_result_content.startswith("[POLICY DENIED]")


def test_within_the_same_turn_a_prior_setter_call_satisfies_a_later_gate() -> None:
    """If the model calls read_file AND bash in the same LLM turn (one
    tool_use batch), read_file running first must satisfy bash's gate
    within that same batch — no artificial extra round-trip required."""
    calls: list[str] = []

    def read_file_handler(inp: dict[str, Any]) -> str:
        calls.append("read_file")
        return "file contents"

    def bash_handler(inp: dict[str, Any]) -> str:
        calls.append("bash")
        return "real output"

    cfg = VerificationConfig(
        set_by={"read_file": "read"},
        blocking_until={"bash": "read"},
    )
    node = _make_execute_tools_node(
        tool_handlers={"read_file": read_file_handler, "bash": bash_handler},
        verification_cfg=cfg,
        human_approval_required=False,
        tools=[_READ_FILE_TOOL, _BASH_TOOL],
    )

    state: AgentRunState = {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu1",
                        "name": "read_file",
                        "input": {"path": "a.py"},
                    },
                    {
                        "type": "tool_use",
                        "id": "tu2",
                        "name": "bash",
                        "input": {"command": "echo hi"},
                    },
                ],
            }
        ],
        "verification": {"read": False},
        "result": {},
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
        "turns": 1,
        "confidence": 1.0,
        "critique_result": {},
    }

    result = node(state)

    assert calls == ["read_file", "bash"]
    bash_result_content = result["messages"][-1]["content"][1]["content"]
    assert bash_result_content == "real output"


def test_dependency_security_agent_bash_requires_read_first() -> None:
    """The real, live wiring: dependency_security_agent's own _CFG."""
    handler_called = {"value": False}

    def bash_handler(inp: dict[str, Any]) -> str:
        handler_called["value"] = True
        return "pip-audit output"

    node = _make_execute_tools_node(
        tool_handlers={"bash": bash_handler},
        verification_cfg=DEP_SEC_CFG,
        human_approval_required=False,
        tools=[_BASH_TOOL],
    )

    denied = node(
        _tool_use_state(
            "bash",
            {"command": "pip-audit"},
            verification={"read": False, "audited": False},
        )
    )
    denied_content = denied["messages"][-1]["content"][0]["content"]
    assert denied_content.startswith("[POLICY DENIED]")
    assert handler_called["value"] is False

    allowed = node(
        _tool_use_state(
            "bash",
            {"command": "pip-audit"},
            verification={"read": True, "audited": False},
        )
    )
    allowed_content = allowed["messages"][-1]["content"][0]["content"]
    assert allowed_content == "pip-audit output"
    assert handler_called["value"] is True
