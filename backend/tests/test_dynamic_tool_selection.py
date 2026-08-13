"""plan14 Day 1 Task 1 — Dynamic Tool Selection.

`ToolDiscovery.filter_runtime_tools()` narrows an agent's static tool list to
what can actually run right now:

1. Availability — the tool has a live entry in `tool_handlers` (the
   zero-false-negative signal; unlike `check_availability()`, this correctly
   keeps every agent's own locally-defined `submit_*` closure).
2. Contract drift — a high-risk tool must also be declared in the agent's own
   `capability_registry` `AgentCapability.tools`. Non-high-risk tools and
   agents with no registered capability entry are not narrowed by this check.

It never adds a tool absent from the input list, and preserves order.

Uses a fresh `ToolDiscovery()` instance for unit tests (not the process
singleton), same convention as tests/test_tool_discovery.py, so these tests
don't depend on which agent modules happen to already be imported and don't
leak synthetic capability registrations into other test files.
"""

from __future__ import annotations

import contextlib
import os
from typing import Any
from unittest.mock import patch

from app.fleet.capability_registry import AgentCapability, get_capability_registry
from app.fleet.tool_discovery import ToolDiscovery, filter_runtime_tools


def _register_test_agent(
    name: str, tools: list[str], capabilities: list[str] | None = None
) -> None:
    # Registry is a process-wide singleton (same hazard class as
    # conftest.py's db-engine/semaphore/circuit-breaker resets) — a capability
    # tag shared across two different registered agent names trips
    # tests/test_gap53_doc_generators.py's fleet-wide "no duplicate capability
    # tags" guard for the rest of the pytest session, regardless of file
    # execution order. Default to a tag derived from the agent's own name so
    # multiple synthetic test agents registered in this file can never
    # collide with each other or with any real agent.
    get_capability_registry().register(
        AgentCapability(
            name=name,
            description="test agent",
            tools=tools,
            input_types=["text"],
            output_types=["text"],
            capabilities=capabilities or [f"{name}__cap"],
        )
    )


def _names(tools: list[dict[str, Any]]) -> set[str]:
    return {str(t["name"]) for t in tools}


# ---------------------------------------------------------------------------
# Unit tests — ToolDiscovery.filter_runtime_tools direct
# ---------------------------------------------------------------------------


def test_keeps_tool_with_live_handler() -> None:
    d = ToolDiscovery()
    tools = [{"name": "read_file"}]
    handlers = {"read_file": lambda inp: "ok"}

    result = d.filter_runtime_tools("dts_agent_a", tools, handlers)

    assert _names(result) == {"read_file"}


def test_drops_tool_without_live_handler() -> None:
    d = ToolDiscovery()
    tools = [{"name": "read_file"}, {"name": "dts_ghost_tool"}]
    handlers = {"read_file": lambda inp: "ok"}  # dts_ghost_tool absent

    result = d.filter_runtime_tools("dts_agent_b", tools, handlers)

    assert _names(result) == {"read_file"}


def test_never_adds_a_tool_absent_from_the_input_list() -> None:
    d = ToolDiscovery()
    tools = [{"name": "read_file"}]
    # Handlers dict has extra entries the static tool list never mentioned.
    handlers = {"read_file": lambda inp: "ok", "bash": lambda inp: "ok"}

    result = d.filter_runtime_tools("dts_agent_c", tools, handlers)

    assert _names(result) == {"read_file"}


def test_preserves_input_order() -> None:
    d = ToolDiscovery()
    tools = [{"name": "c"}, {"name": "a"}, {"name": "b"}]
    handlers = {"a": None, "b": None, "c": None}

    result = d.filter_runtime_tools("dts_agent_order", tools, handlers)

    assert [t["name"] for t in result] == ["c", "a", "b"]


def test_high_risk_tool_dropped_when_not_declared_in_capability() -> None:
    _register_test_agent("dts_agent_no_bash", tools=["read_file"])
    d = ToolDiscovery()
    tools = [{"name": "read_file"}, {"name": "bash"}]
    handlers = {"read_file": None, "bash": None}

    result = d.filter_runtime_tools("dts_agent_no_bash", tools, handlers)

    assert _names(result) == {"read_file"}


def test_high_risk_tool_kept_when_declared_in_capability() -> None:
    _register_test_agent("dts_agent_with_bash", tools=["read_file", "bash"])
    d = ToolDiscovery()
    tools = [{"name": "read_file"}, {"name": "bash"}]
    handlers = {"read_file": None, "bash": None}

    result = d.filter_runtime_tools("dts_agent_with_bash", tools, handlers)

    assert _names(result) == {"read_file", "bash"}


def test_non_high_risk_tool_unaffected_by_capability_declaration() -> None:
    """read_file is not high-risk, so it's kept even though the registered
    capability entry doesn't declare it — only high-risk tools are narrowed
    by the contract-drift check."""
    _register_test_agent("dts_agent_sparse_contract", tools=["bash"])
    d = ToolDiscovery()
    tools = [{"name": "read_file"}]
    handlers = {"read_file": None}

    result = d.filter_runtime_tools("dts_agent_sparse_contract", tools, handlers)

    assert _names(result) == {"read_file"}


def test_unregistered_agent_only_availability_check_applies() -> None:
    """No AgentCapability entry (e.g. a synthetic/test role_name) means the
    contract-drift check is skipped entirely — fail open on that check, not
    on availability. This matches how run_agent_graph is called today for
    ~10 synthetic test role names with no registry entry."""
    d = ToolDiscovery()
    tools = [{"name": "bash"}]
    handlers = {"bash": None}

    result = d.filter_runtime_tools("dts_totally_unregistered_agent", tools, handlers)

    assert _names(result) == {"bash"}


def test_module_level_filter_runtime_tools_delegates_to_singleton() -> None:
    _register_test_agent("dts_agent_singleton_check", tools=["read_file"])
    tools = [{"name": "read_file"}, {"name": "bash"}]
    handlers = {"read_file": None, "bash": None}

    result = filter_runtime_tools("dts_agent_singleton_check", tools, handlers)

    assert _names(result) == {"read_file"}


# ---------------------------------------------------------------------------
# Regression — real production tool lists must never gain tools, and today's
# actual (handler, contract) pairing for these three real agents is known to
# be aligned (verified by reading each agent's own module), so nothing should
# be unexpectedly dropped either.
# ---------------------------------------------------------------------------


def test_real_spike_agent_tool_list_unchanged_when_handlers_complete() -> None:
    from app.agents.spike_agent import _TOOLS as spike_tools

    handlers = dict.fromkeys(t["name"] for t in spike_tools)
    result = filter_runtime_tools("spike_agent", spike_tools, handlers)
    assert _names(result) == _names(spike_tools)


def test_real_qa_agent_tool_list_unchanged_when_handlers_complete() -> None:
    from app.agents.tools import QA_TOOLS

    handlers = dict.fromkeys(t["name"] for t in QA_TOOLS)
    result = filter_runtime_tools("qa", QA_TOOLS, handlers)
    assert _names(result) == _names(QA_TOOLS)


def test_real_bug_fix_agent_tool_list_unchanged_when_handlers_complete() -> None:
    from app.agents.tools import BUG_FIX_TOOLS

    handlers = dict.fromkeys(t["name"] for t in BUG_FIX_TOOLS)
    result = filter_runtime_tools("bug_fix", BUG_FIX_TOOLS, handlers)
    assert _names(result) == _names(BUG_FIX_TOOLS)


def test_filter_never_expands_any_real_registered_agents_declared_tools() -> None:
    """Sweep of the real, process-populated capability registry (agent
    modules register themselves at import time — importing the three agents
    above is enough to guarantee at least a few real entries exist). For
    every registered agent, treat its own declared tools as both the static
    list and the available-handlers set; the filter must never grow it."""
    import app.agents.bug_fix  # noqa: F401
    import app.agents.qa  # noqa: F401
    import app.agents.spike_agent  # noqa: F401

    checked_any = False
    for cap in get_capability_registry().all():
        if not cap.tools:
            continue
        checked_any = True
        static_tools = [{"name": name} for name in cap.tools]
        handlers = dict.fromkeys(cap.tools)
        result = filter_runtime_tools(cap.name, static_tools, handlers)
        assert _names(result) <= set(cap.tools), (
            f"filter_runtime_tools added a tool not in {cap.name}'s own "
            f"declared contract"
        )
    assert checked_any, "expected at least one real agent to be registered"


# ---------------------------------------------------------------------------
# Integration — run_agent_graph actually applies the filter at runtime, using
# the same mocked-Anthropic-client harness established in
# tests/test_task_images.py / tests/test_phase37_quality_gate.py.
# ---------------------------------------------------------------------------

SUBMIT_TOOL = {
    "name": "submit_result",
    "description": "Submit",
    "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
}
GHOST_TOOL = {
    "name": "dts_ghost_tool",
    "description": "A tool with no live handler.",
    "input_schema": {"type": "object", "properties": {}},
}
BASH_TOOL = {
    "name": "bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}


def _fake_create(**kwargs: Any) -> Any:
    return type(
        "R",
        (),
        {
            "content": [type("B", (), {"type": "text", "text": "{}"})()],
            "usage": type("U", (), {"input_tokens": 5, "output_tokens": 5})(),
            "stop_reason": "end_turn",
        },
    )()


@contextlib.contextmanager
def _override_dynamic_tool_selection(enabled: bool):  # type: ignore[no-untyped-def]
    import app.config as cfg

    os.environ["DYNAMIC_TOOL_SELECTION_ENABLED"] = "true" if enabled else "false"
    cfg._settings = None
    try:
        yield
    finally:
        os.environ.pop("DYNAMIC_TOOL_SELECTION_ENABLED", None)
        cfg._settings = None


def _run_and_capture_tools(
    *, tools: list[dict[str, Any]], tool_handlers: dict[str, Any], role_name: str
) -> list[dict[str, Any]]:
    from app.agents.base_graph import VerificationConfig, run_agent_graph

    captured: dict[str, Any] = {}

    def _capturing_create(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_create(**kwargs)

    with (
        patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"),
        patch("anthropic.Anthropic") as mock_anthropic_cls,
    ):
        mock_anthropic_cls.return_value.messages.create.side_effect = _capturing_create
        run_agent_graph(
            role_name=role_name,
            model="claude-haiku-4-5-20251001",
            tools=tools,
            tool_handlers=tool_handlers,
            verification_cfg=VerificationConfig(
                set_by={}, reset_by=(), reset_keys=(), enforce_in_result={}, initial={}
            ),
            initial_message="do a task",
            enable_planning=False,
            enable_memory=False,
            enable_reflection=False,
            enable_lesson=False,
            max_turns=1,
        )
    return list(captured.get("tools") or [])


def test_run_agent_graph_strips_tool_without_live_handler_when_flag_enabled() -> None:
    with _override_dynamic_tool_selection(True):
        sent_tools = _run_and_capture_tools(
            tools=[SUBMIT_TOOL, GHOST_TOOL],
            tool_handlers={"submit_result": lambda inp: "ok"},
            role_name="dts_integration_test_agent_unregistered",
        )

    assert _names(sent_tools) == {"submit_result"}


def test_run_agent_graph_passes_tools_unchanged_when_flag_disabled() -> None:
    with _override_dynamic_tool_selection(False):
        sent_tools = _run_and_capture_tools(
            tools=[SUBMIT_TOOL, GHOST_TOOL],
            tool_handlers={"submit_result": lambda inp: "ok"},
            role_name="dts_integration_test_agent_flag_off",
        )

    assert _names(sent_tools) == {"submit_result", "dts_ghost_tool"}


def test_run_agent_graph_drops_high_risk_tool_not_in_registered_contract() -> None:
    _register_test_agent(
        "dts_contract_drift_agent", tools=["submit_result"], capabilities=["dts_cap"]
    )
    with _override_dynamic_tool_selection(True):
        sent_tools = _run_and_capture_tools(
            tools=[SUBMIT_TOOL, BASH_TOOL],
            tool_handlers={
                "submit_result": lambda inp: "ok",
                "bash": lambda inp: "ok",
            },
            role_name="dts_contract_drift_agent",
        )

    assert _names(sent_tools) == {"submit_result"}
