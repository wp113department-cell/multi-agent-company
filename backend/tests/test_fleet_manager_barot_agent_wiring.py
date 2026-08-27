"""Tests for FleetManager.select()'s barot_agent gap-fill hook
(_decline_or_fill_gap). Unlike test_fleet_manager.py's scoring tests (which
use isolated, constructor-injected CapabilityRegistry/AgentRegistry
instances), these use the real global singleton via get_fleet_manager() —
same precedent as test_fleet_manager.py's own TestReferenceAgents class —
because barot_agent (like every real agent's own _register() hook) always
registers into the global capability_registry/agent_registry, not whatever
registry a specific FleetManager instance happens to be constructed with.

Real Claude API calls are always mocked."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.agents.temporary_agent import get_temporary_agent_pool
from app.fleet.fleet_manager import get_fleet_manager


def _tool_use_response(tool_names, briefing):
    block = SimpleNamespace(
        type="tool_use",
        name="plan_tool_profile",
        input={"tool_names": tool_names, "briefing": briefing},
    )
    return SimpleNamespace(content=[block])


@pytest.fixture(autouse=True)
def _cleanup_settings_and_pool():
    yield
    import app.config as cfg_module

    cfg_module._settings = None
    # Best-effort: scrap anything a test left registered.
    pool = get_temporary_agent_pool()
    for name in list(pool._slots.keys()):
        pool.scrap(name, reason="test_cleanup")


def test_select_with_no_task_context_declines_gap_fill_unchanged() -> None:
    """Every pre-existing select() caller that omits task_id/
    task_description must see byte-for-byte the same None as before this
    feature existed — this is the regression test for that guarantee."""
    with patch("app.agents.base_graph._call_anthropic") as mock_call:
        plan = get_fleet_manager().select("definitely_unregistered_capability_abc")
    assert plan is None
    mock_call.assert_not_called()


def test_select_with_task_context_fills_gap_and_returns_dispatch_plan() -> None:
    response = _tool_use_response(["read_file"], "read the relevant files")

    with patch("app.agents.base_graph._make_client", return_value=MagicMock()), patch(
        "app.agents.base_graph._call_anthropic", return_value=response
    ):
        plan = get_fleet_manager().select(
            "unregistered_capability_via_select_xyz",
            task_id="101",
            task_description="a task needing a capability nothing declares",
            repo_path="/tmp",
        )

    assert plan is not None
    assert plan.agent_name.startswith("temporary_agent-101-")
    assert plan.capability.capabilities == ["unregistered_capability_via_select_xyz"]
    assert plan.instance.is_available is True  # SLEEP, never auto-started


def test_select_with_barot_agent_disabled_declines_even_with_task_context(
    monkeypatch,
) -> None:
    monkeypatch.setenv("BAROT_AGENT_ENABLED", "false")
    import app.config as cfg_module

    cfg_module._settings = None

    with patch("app.agents.base_graph._call_anthropic") as mock_call:
        plan = get_fleet_manager().select(
            "unregistered_capability_disabled_test",
            task_id="102",
            task_description="task",
            repo_path="/tmp",
        )
    assert plan is None
    mock_call.assert_not_called()


def test_status_includes_barot_agent_pool_state() -> None:
    status = get_fleet_manager().status()
    assert "barot_agent" in status
    assert "enabled" in status["barot_agent"]
    assert "max_concurrent" in status["barot_agent"]
    assert "slots" in status["barot_agent"]


def test_dispatch_marks_the_spawned_temp_agent_running() -> None:
    """dispatch() calls start_task() on whatever agent_name select() returns
    — this must work identically for a barot-spawned temp agent as for any
    real agent, with no special-casing."""
    response = _tool_use_response(["read_file"], "briefing")

    with patch("app.agents.base_graph._make_client", return_value=MagicMock()), patch(
        "app.agents.base_graph._call_anthropic", return_value=response
    ):
        result = get_fleet_manager().dispatch(
            required_capability="unregistered_capability_dispatch_test",
            task_id="103",
            task_payload={"description": "a task", "repo_path": "/tmp"},
        )

    assert result["status"] == "dispatched"
    agent_name = result["agent_name"]
    assert agent_name.startswith("temporary_agent-103-")

    from app.fleet.agent_registry import get_agent_registry

    instance = get_agent_registry().get(agent_name)
    assert instance is not None
    assert instance.current_task_id == "103"
