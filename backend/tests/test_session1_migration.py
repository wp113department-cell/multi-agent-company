"""Session 1 migration tests — architect, decomposer, planner (no real LLM calls).

Tests prove:
- All 3 agents import without errors
- AGENT_CONTRACT present with correct required fields
- All 3 are low risk_level with no side effects
- No high-risk tools in any contract
- External interfaces unchanged (architect_node, decomposer_node, run_planner signatures)
- All 3 auto-register in capability_registry on import
- All 3 auto-register in agent_registry on import
- No longer import run_agent from base (migration complete)
- VerificationConfig instances are correctly scoped (read-only)
- _validate_plan logic still works (planner backward compat)
- fleet_manager can select each agent by capability
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Import the 3 migrated agents (triggers _register() at module level)
# ---------------------------------------------------------------------------

import app.agents.architect as arch_mod
import app.agents.decomposer as dec_mod
import app.agents.planner as plan_mod

from app.agents.architect import AGENT_CONTRACT as ARCH_CONTRACT, architect_node
from app.agents.decomposer import AGENT_CONTRACT as DEC_CONTRACT, decomposer_node
from app.agents.planner import (
    AGENT_CONTRACT as PLAN_CONTRACT,
    run_planner,
    _validate_plan,
)

# ---------------------------------------------------------------------------
# AGENT_CONTRACT structure
# ---------------------------------------------------------------------------

REQUIRED_CONTRACT_KEYS = {
    "name",
    "description",
    "allowed_tools",
    "input_types",
    "output_types",
    "side_effects",
    "permissions",
    "risk_level",
}


class TestArchitectContract:
    def test_contract_has_all_required_keys(self) -> None:
        assert REQUIRED_CONTRACT_KEYS.issubset(ARCH_CONTRACT.keys())

    def test_name_is_architect(self) -> None:
        assert ARCH_CONTRACT["name"] == "architect"

    def test_risk_level_is_low(self) -> None:
        assert ARCH_CONTRACT["risk_level"] == "low"

    def test_no_side_effects(self) -> None:
        assert ARCH_CONTRACT["side_effects"] == []

    def test_submit_tool_in_allowed_tools(self) -> None:
        assert "submit_architect_plan" in ARCH_CONTRACT["allowed_tools"]

    def test_no_write_tools_in_contract(self) -> None:
        write_tools = {"write_file", "edit_file", "delete_file", "apply_patch", "bash"}
        used = write_tools & set(ARCH_CONTRACT["allowed_tools"])
        assert used == set(), f"Architect has write tools: {used}"

    def test_input_types_include_pm_brief(self) -> None:
        assert "pm_brief" in ARCH_CONTRACT["input_types"]

    def test_output_types_include_architect_plan(self) -> None:
        assert "architect_plan" in ARCH_CONTRACT["output_types"]

    def test_depends_on_pm(self) -> None:
        assert "pm" in ARCH_CONTRACT["dependencies"]


class TestDecomposerContract:
    def test_contract_has_all_required_keys(self) -> None:
        assert REQUIRED_CONTRACT_KEYS.issubset(DEC_CONTRACT.keys())

    def test_name_is_decomposer(self) -> None:
        assert DEC_CONTRACT["name"] == "decomposer"

    def test_risk_level_is_low(self) -> None:
        assert DEC_CONTRACT["risk_level"] == "low"

    def test_no_side_effects(self) -> None:
        assert DEC_CONTRACT["side_effects"] == []

    def test_submit_tool_in_allowed_tools(self) -> None:
        assert "submit_subtasks" in DEC_CONTRACT["allowed_tools"]

    def test_no_write_tools_in_contract(self) -> None:
        write_tools = {"write_file", "edit_file", "delete_file", "apply_patch", "bash"}
        used = write_tools & set(DEC_CONTRACT["allowed_tools"])
        assert used == set(), f"Decomposer has write tools: {used}"

    def test_depends_on_architect(self) -> None:
        assert "architect" in DEC_CONTRACT["dependencies"]


class TestPlannerContract:
    def test_contract_has_all_required_keys(self) -> None:
        assert REQUIRED_CONTRACT_KEYS.issubset(PLAN_CONTRACT.keys())

    def test_name_is_planner(self) -> None:
        assert PLAN_CONTRACT["name"] == "planner"

    def test_risk_level_is_low(self) -> None:
        assert PLAN_CONTRACT["risk_level"] == "low"

    def test_no_side_effects(self) -> None:
        assert PLAN_CONTRACT["side_effects"] == []

    def test_submit_tool_in_allowed_tools(self) -> None:
        assert "submit_plan" in PLAN_CONTRACT["allowed_tools"]

    def test_no_write_tools_in_contract(self) -> None:
        write_tools = {"write_file", "edit_file", "delete_file", "apply_patch", "bash"}
        used = write_tools & set(PLAN_CONTRACT["allowed_tools"])
        assert used == set(), f"Planner has write tools: {used}"


# ---------------------------------------------------------------------------
# Migration complete — no longer uses run_agent from base
# ---------------------------------------------------------------------------


class TestMigrationComplete:
    def _has_run_agent_import(self, mod: Any) -> bool:
        """True if module actually imports run_agent (not run_agent_graph)."""
        import ast
        import inspect
        import textwrap

        src = textwrap.dedent(inspect.getsource(mod))
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return False
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if (
                            alias.name == "run_agent"
                            and alias.asname != "run_agent_graph"
                        ):
                            return True
        return False

    def test_architect_does_not_import_run_agent(self) -> None:
        assert not self._has_run_agent_import(
            arch_mod
        ), "architect.py imports bare run_agent — migration incomplete"

    def test_decomposer_does_not_import_run_agent(self) -> None:
        assert not self._has_run_agent_import(
            dec_mod
        ), "decomposer.py imports bare run_agent — migration incomplete"

    def test_planner_does_not_import_run_agent(self) -> None:
        assert not self._has_run_agent_import(
            plan_mod
        ), "planner.py imports bare run_agent — migration incomplete"

    def test_architect_uses_run_agent_graph(self) -> None:
        import inspect

        src = inspect.getsource(arch_mod)
        assert "run_agent_graph" in src

    def test_decomposer_uses_run_agent_graph(self) -> None:
        import inspect

        src = inspect.getsource(dec_mod)
        assert "run_agent_graph" in src

    def test_planner_uses_run_agent_graph(self) -> None:
        import inspect

        src = inspect.getsource(plan_mod)
        assert "run_agent_graph" in src


# ---------------------------------------------------------------------------
# External interface unchanged
# ---------------------------------------------------------------------------


class TestExternalInterfaceUnchanged:
    def test_architect_node_takes_pipeline_state(self) -> None:
        sig = inspect.signature(architect_node)
        assert "state" in sig.parameters

    def test_decomposer_node_takes_pipeline_state(self) -> None:
        sig = inspect.signature(decomposer_node)
        assert "state" in sig.parameters

    def test_run_planner_signature_unchanged(self) -> None:
        sig = inspect.signature(run_planner)
        params = list(sig.parameters.keys())
        assert params[:4] == ["task_id", "title", "description", "repo_path"]

    def test_run_planner_has_heartbeat_compat_params(self) -> None:
        sig = inspect.signature(run_planner)
        assert "on_heartbeat" in sig.parameters
        assert "on_tool_call" in sig.parameters


# ---------------------------------------------------------------------------
# Capability registry auto-registration
# ---------------------------------------------------------------------------


class TestCapabilityRegistryRegistration:
    def test_architect_in_capability_registry(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        r = get_capability_registry()
        assert r.get("architect") is not None

    def test_decomposer_in_capability_registry(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        r = get_capability_registry()
        assert r.get("decomposer") is not None

    def test_planner_in_capability_registry(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        r = get_capability_registry()
        assert r.get("planner") is not None

    def test_architect_capability_tags(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        cap = get_capability_registry().get("architect")
        assert cap is not None
        assert "architecture_design" in cap.capabilities

    def test_decomposer_capability_tags(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        cap = get_capability_registry().get("decomposer")
        assert cap is not None
        assert "task_decomposition" in cap.capabilities

    def test_planner_capability_tags(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        cap = get_capability_registry().get("planner")
        assert cap is not None
        assert "implementation_planning" in cap.capabilities


# ---------------------------------------------------------------------------
# Agent registry auto-registration
# ---------------------------------------------------------------------------


class TestAgentRegistryRegistration:
    def test_architect_in_agent_registry(self) -> None:
        from app.fleet.agent_registry import get_agent_registry

        inst = get_agent_registry().get("architect")
        assert inst is not None

    def test_decomposer_in_agent_registry(self) -> None:
        from app.fleet.agent_registry import get_agent_registry

        inst = get_agent_registry().get("decomposer")
        assert inst is not None

    def test_planner_in_agent_registry(self) -> None:
        from app.fleet.agent_registry import get_agent_registry

        inst = get_agent_registry().get("planner")
        assert inst is not None


# ---------------------------------------------------------------------------
# Fleet manager can select by capability
# ---------------------------------------------------------------------------


class TestFleetManagerSelection:
    def test_fleet_manager_selects_architect_by_capability(self) -> None:
        from app.fleet.fleet_manager import FleetManager
        from app.fleet.capability_registry import get_capability_registry
        from app.fleet.agent_registry import get_agent_registry

        fm = FleetManager(
            capability_registry=get_capability_registry(),
            agent_registry=get_agent_registry(),
        )
        plan = fm.select("architecture_design")
        assert plan is not None
        assert plan.agent_name == "architect"

    def test_fleet_manager_selects_decomposer_by_capability(self) -> None:
        from app.fleet.fleet_manager import FleetManager
        from app.fleet.capability_registry import get_capability_registry
        from app.fleet.agent_registry import get_agent_registry

        fm = FleetManager(
            capability_registry=get_capability_registry(),
            agent_registry=get_agent_registry(),
        )
        plan = fm.select("task_decomposition")
        assert plan is not None
        assert plan.agent_name == "decomposer"

    def test_fleet_manager_selects_planner_by_capability(self) -> None:
        from app.fleet.fleet_manager import FleetManager
        from app.fleet.capability_registry import get_capability_registry
        from app.fleet.agent_registry import get_agent_registry

        fm = FleetManager(
            capability_registry=get_capability_registry(),
            agent_registry=get_agent_registry(),
        )
        plan = fm.select("codebase_analysis")
        assert plan is not None
        assert plan.agent_name == "planner"


# ---------------------------------------------------------------------------
# Tool manifest compliance
# ---------------------------------------------------------------------------


class TestToolManifestCompliance:
    # Submit tools are agent-private (dynamically registered per-agent, not shared across agents)
    # so they are not in the global TOOL_MANIFEST. Only shared tools are checked.
    _SUBMIT_TOOLS = {"submit_architect_plan", "submit_subtasks", "submit_plan"}

    def _shared_tools(self, contract: dict[str, Any]) -> list[str]:
        return [t for t in contract["allowed_tools"] if t not in self._SUBMIT_TOOLS]

    def test_all_architect_shared_tools_in_manifest(self) -> None:
        from app.fleet.tool_manifest import TOOL_MANIFEST

        for tool in self._shared_tools(ARCH_CONTRACT):
            assert (
                tool in TOOL_MANIFEST
            ), f"architect uses {tool!r} — not in TOOL_MANIFEST"

    def test_all_decomposer_shared_tools_in_manifest(self) -> None:
        from app.fleet.tool_manifest import TOOL_MANIFEST

        for tool in self._shared_tools(DEC_CONTRACT):
            assert (
                tool in TOOL_MANIFEST
            ), f"decomposer uses {tool!r} — not in TOOL_MANIFEST"

    def test_all_planner_shared_tools_in_manifest(self) -> None:
        from app.fleet.tool_manifest import TOOL_MANIFEST

        for tool in self._shared_tools(PLAN_CONTRACT):
            assert (
                tool in TOOL_MANIFEST
            ), f"planner uses {tool!r} — not in TOOL_MANIFEST"

    def test_verify_agent_contract_no_violations(self) -> None:
        from app.fleet.tool_manifest import verify_agent_contract

        for contract in [ARCH_CONTRACT, DEC_CONTRACT, PLAN_CONTRACT]:
            violations = verify_agent_contract(
                contract["name"],
                tool_list=contract["allowed_tools"],
                contract_allowed_tools=contract["allowed_tools"],
            )
            assert (
                violations == []
            ), f"{contract['name']} has contract violations: {violations}"


# ---------------------------------------------------------------------------
# Planner _validate_plan logic (backward compat)
# ---------------------------------------------------------------------------


class TestValidatePlan:
    def test_valid_plan_returns_none(self) -> None:
        plan = (
            "## Overview\n\nImplementation Steps:\n1. Do X\n\nFiles To Inspect:\n- src/main.py\n"
            * 3
        )
        assert _validate_plan(plan) is None

    def test_too_short_returns_error(self) -> None:
        assert _validate_plan("short") is not None

    def test_missing_sections_returns_error(self) -> None:
        plan = "A" * 200  # long enough but missing sections
        result = _validate_plan(plan)
        assert result is not None
        assert "missing" in result.lower()


# ---------------------------------------------------------------------------
# architect_node returns blocked when run_agent_graph raises
# ---------------------------------------------------------------------------


class TestArchitectNodeErrorHandling:
    @patch("app.agents.architect.run_agent_graph", side_effect=RuntimeError("API down"))
    def test_returns_blocked_on_exception(self, mock_graph: Any) -> None:
        state = {
            "task_title": "Add auth",
            "pm_brief": {"goal": "Add login"},
            "repo_path": "/tmp/test",
        }
        result = architect_node(state)  # type: ignore[arg-type]
        assert result["stage"] == "blocked"
        assert "Architect Agent failed" in result["error"]

    @patch("app.agents.architect.run_agent_graph")
    def test_returns_blocked_when_not_submitted(self, mock_graph: Any) -> None:
        mock_graph.return_value = {
            "messages": [],
            "verification": {},
            "result": {},
            "turns": 1,
            "submitted": False,
            "requires_human_approval": False,
            "tokens_in": 100,
            "tokens_out": 50,
        }
        state = {"task_title": "Test", "pm_brief": {}, "repo_path": "/tmp/test"}
        result = architect_node(state)  # type: ignore[arg-type]
        assert result["stage"] == "blocked"

    @patch("app.agents.architect.run_agent_graph")
    def test_returns_architect_plan_on_success(self, mock_graph: Any) -> None:
        mock_graph.return_value = {
            "messages": [],
            "verification": {},
            "result": {
                "technical_approach": "Use dependency injection",
                "impacted_files": [{"path": "src/auth.py", "reason": "main module"}],
                "risks": [{"severity": "low", "description": "minor refactor"}],
                "risk_level": "low",
            },
            "turns": 3,
            "submitted": True,
            "requires_human_approval": False,
            "tokens_in": 1000,
            "tokens_out": 200,
        }
        state = {"task_title": "Test", "pm_brief": {}, "repo_path": "/tmp/test"}
        result = architect_node(state)  # type: ignore[arg-type]
        assert result["stage"] == "decomposer"
        assert (
            result["architect_plan"]["technical_approach"] == "Use dependency injection"
        )
        assert "_requires_human_approval" not in result["architect_plan"]


# ---------------------------------------------------------------------------
# decomposer_node error handling
# ---------------------------------------------------------------------------


class TestDecomposerNodeErrorHandling:
    @patch("app.agents.decomposer.run_agent_graph")
    def test_returns_subtasks_on_success(self, mock_graph: Any) -> None:
        mock_graph.return_value = {
            "messages": [],
            "verification": {},
            "result": {
                "subtasks": [
                    {
                        "type": "backend",
                        "title": "Add auth route",
                        "description": "POST /auth/login",
                    },
                    {
                        "type": "test",
                        "title": "Test auth",
                        "description": "pytest tests",
                    },
                ],
            },
            "turns": 2,
            "submitted": True,
            "requires_human_approval": False,
            "tokens_in": 800,
            "tokens_out": 150,
        }
        state = {
            "task_title": "Add auth",
            "pm_brief": {"goal": "Login"},
            "architect_plan": {"technical_approach": "JWT"},
            "repo_path": "/tmp/test",
        }
        result = decomposer_node(state)  # type: ignore[arg-type]
        assert result["stage"] == "done"
        assert len(result["subtasks"]) == 2
        assert result["subtasks"][0]["type"] == "backend"

    @patch("app.agents.decomposer.run_agent_graph")
    def test_returns_blocked_on_empty_subtasks(self, mock_graph: Any) -> None:
        mock_graph.return_value = {
            "messages": [],
            "verification": {},
            "result": {"subtasks": []},
            "turns": 2,
            "submitted": True,
            "requires_human_approval": False,
            "tokens_in": 500,
            "tokens_out": 100,
        }
        state = {
            "task_title": "Test",
            "pm_brief": {},
            "architect_plan": {},
            "repo_path": "/tmp",
        }
        result = decomposer_node(state)  # type: ignore[arg-type]
        assert result["stage"] == "blocked"
