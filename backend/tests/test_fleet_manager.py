"""Tests for Fleet OS fleet_manager.py — Phase F3.

Key assertion: fleet_manager selects agents via registry lookup, NOT by hardcoded name.
"""
from __future__ import annotations

import pytest

from app.fleet.agent_registry import AgentRegistry, AgentState
from app.fleet.capability_registry import AgentCapability, CapabilityRegistry
from app.fleet.fleet_manager import FleetManager


def _setup(capabilities: list[AgentCapability]) -> FleetManager:
    caps = CapabilityRegistry()
    agents = AgentRegistry()
    for cap in capabilities:
        caps.register(cap)
        agents.register(cap.name)
    return FleetManager(capability_registry=caps, agent_registry=agents)


def _cap(name: str, capabilities: list[str], success_rate: float = 1.0, risk_level: str = "low") -> AgentCapability:
    return AgentCapability(
        name=name,
        description=f"Test agent {name}",
        tools=[],
        input_types=[],
        output_types=[],
        capabilities=capabilities,
        success_rate=success_rate,
        risk_level=risk_level,
    )


class TestRegistryLookup:
    def test_selects_via_registry_not_hardcoded_name(self) -> None:
        fm = _setup([_cap("dynamic_agent", ["special_task"])])
        plan = fm.select("special_task")
        assert plan is not None
        assert plan.agent_name == "dynamic_agent"

    def test_returns_none_when_no_agent_covers_capability(self) -> None:
        fm = _setup([_cap("agent_a", ["capability_x"])])
        plan = fm.select("capability_y")
        assert plan is None

    def test_returns_none_when_all_agents_are_running(self) -> None:
        fm = _setup([_cap("busy_agent", ["work"])])
        fm._agents.start_task("busy_agent", "task-99")
        plan = fm.select("work")
        assert plan is None


class TestScoring:
    def test_prefers_higher_success_rate(self) -> None:
        fm = _setup([
            _cap("good", ["coding"], success_rate=0.95),
            _cap("bad", ["coding"], success_rate=0.50),
        ])
        plan = fm.select("coding")
        assert plan is not None
        assert plan.agent_name == "good"

    def test_prefers_healthy_over_degraded(self) -> None:
        fm = _setup([
            _cap("agent_a", ["coding"]),
            _cap("agent_b", ["coding"]),
        ])
        fm._agents.get("agent_a").health = "degraded"
        plan = fm.select("coding")
        assert plan is not None
        assert plan.agent_name == "agent_b"

    def test_excludes_unhealthy_agents(self) -> None:
        fm = _setup([_cap("sick", ["coding"])])
        fm._agents.get("sick").health = "unhealthy"
        plan = fm.select("coding")
        assert plan is None

    def test_prefer_low_risk_filters_high_risk(self) -> None:
        fm = _setup([
            _cap("safe", ["deploy"], risk_level="low"),
            _cap("risky", ["deploy"], risk_level="high"),
        ])
        plan = fm.select("deploy", prefer_low_risk=True)
        assert plan is not None
        assert plan.agent_name == "safe"


class TestDispatch:
    def test_dispatch_marks_agent_as_running(self) -> None:
        fm = _setup([_cap("worker", ["processing"])])
        result = fm.dispatch("processing", "task-42", {})
        assert result["status"] == "dispatched"
        assert result["agent_name"] == "worker"
        inst = fm._agents.get("worker")
        assert inst.state == AgentState.RUNNING
        assert inst.current_task_id == "task-42"

    def test_dispatch_returns_no_agent_when_none_available(self) -> None:
        fm = _setup([_cap("worker", ["processing"])])
        fm._agents.start_task("worker", "task-prev")
        result = fm.dispatch("processing", "task-42", {})
        assert result["status"] == "no_agent_available"

    def test_complete_moves_agent_back_to_sleep(self) -> None:
        fm = _setup([_cap("worker", ["processing"])])
        fm.dispatch("processing", "task-42", {})
        fm.complete("worker")
        assert fm._agents.get("worker").state == AgentState.SLEEP

    def test_fail_records_error(self) -> None:
        fm = _setup([_cap("worker", ["processing"])])
        fm.dispatch("processing", "task-42", {})
        fm.fail("worker", "timed out")
        assert fm._agents.get("worker").error_count == 1


class TestStatus:
    def test_status_reflects_registry_state(self) -> None:
        fm = _setup([
            _cap("a", ["cap1"]),
            _cap("b", ["cap2"]),
        ])
        status = fm.status()
        assert status["registered_capabilities"] == 2
        assert status["agent_instances"] == 2
        assert status["available"] == 2
        assert status["running"] == 0


class TestReferenceAgents:
    def test_reference_fleet_manager_can_select_pm(self) -> None:
        from app.fleet.fleet_manager import get_fleet_manager
        fm = get_fleet_manager()
        plan = fm.select("planning")
        assert plan is not None
        assert plan.agent_name == "pm"

    def test_reference_fleet_manager_can_select_bug_fix(self) -> None:
        from app.fleet.fleet_manager import get_fleet_manager
        fm = get_fleet_manager()
        plan = fm.select("bug_fix")
        assert plan is not None
        assert plan.agent_name == "bug_fix"

    def test_reference_fleet_manager_can_select_qa(self) -> None:
        from app.fleet.fleet_manager import get_fleet_manager
        fm = get_fleet_manager()
        plan = fm.select("qa_verification")
        assert plan is not None
        assert plan.agent_name == "qa"
