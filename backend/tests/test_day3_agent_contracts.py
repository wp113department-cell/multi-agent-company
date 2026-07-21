"""Day 3 Agent Contract Tests — 9 agents, same pattern as Day 2.

Covers:
  - AGENT_CONTRACT structure and types (45 parametrized tests, 5 per agent)
  - Capability registry registration (4 tests)
  - Fleet OS flag wiring per agent (9 tests × 1 = 9 tests)
  - FleetManager capability query (9 tests)
  - VerificationConfig enforce_in_result non-empty (9 tests)

Total: 76 tests
"""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Agent list for Day 3
# ---------------------------------------------------------------------------
_DAY3_AGENTS = [
    "app.agents.performance_reviewer",
    "app.agents.style_reviewer",
    "app.agents.sprint_planner",
    "app.agents.business_analyst",
    "app.agents.migration_agent",
    "app.agents.schema_agent",
    "app.agents.ai_engineer",
    "app.agents.cleanup_agent",
    "app.agents.tech_debt_agent",
]

_REQUIRED_CONTRACT_KEYS = {
    "name",
    "description",
    "allowed_tools",
    "input_types",
    "output_types",
    "side_effects",
    "permissions",
    "risk_level",
    "expected_verification",
    "dependencies",
}
_VALID_RISK_LEVELS = {"low", "medium", "high"}

# ---------------------------------------------------------------------------
# Minimal final_state mock that satisfies AgentResult construction
# ---------------------------------------------------------------------------
_FINAL_STATE: dict[str, Any] = {
    "messages": [],
    "verification": {
        "query_explained": True,
        "lint_ran": True,
        "complexity_estimated": True,
        "requirements_read": True,
        "schema_inspected": True,
        "code_tested": True,
        "dead_code_scanned": True,
        "migration_applied": True,
        "coverage_checked": True,
    },
    "result": {
        "summary": "test",
        "findings": [],
        "violations": [],
        "stories": [],
        "migration_file": "",
        "tables": [],
        "eval_results": {},
        "debt_items": [],
        "dead_code_removed": [],
    },
    "submitted": True,
    "requires_human_approval": False,
    "tokens_in": 100,
    "tokens_out": 50,
}


def _mock_settings() -> MagicMock:
    s = MagicMock()
    s.model_coder = "claude-sonnet-test"
    s.model_planner = "claude-sonnet-test"
    s.model_router = "claude-haiku-test"
    s.target_repo_path = "/tmp/repo"
    return s


def _assert_all_flags(kwargs: dict[str, Any], agent_name: str) -> None:
    assert (
        kwargs.get("enable_planning") is True
    ), f"{agent_name}: enable_planning not True"
    assert kwargs.get("enable_memory") is True, f"{agent_name}: enable_memory not True"
    assert (
        kwargs.get("enable_reflection") is True
    ), f"{agent_name}: enable_reflection not True"
    assert kwargs.get("enable_lesson") is True, f"{agent_name}: enable_lesson not True"
    assert (
        kwargs.get("task_description") is not None
    ), f"{agent_name}: task_description missing"
    assert kwargs.get("repo_path") is not None, f"{agent_name}: repo_path missing"
    assert kwargs.get("model_haiku") is not None, f"{agent_name}: model_haiku missing"


# ===========================================================================
# 1 · AGENT_CONTRACT structure (5 tests × 9 agents = 45)
# ===========================================================================


class TestAgentContractFormat:

    @pytest.mark.parametrize("module_path", _DAY3_AGENTS)
    def test_contract_has_required_keys(self, module_path: str) -> None:
        mod = importlib.import_module(module_path)
        contract: dict[str, Any] = mod.AGENT_CONTRACT
        missing = _REQUIRED_CONTRACT_KEYS - set(contract.keys())
        assert not missing, f"{module_path}: AGENT_CONTRACT missing keys: {missing}"

    @pytest.mark.parametrize("module_path", _DAY3_AGENTS)
    def test_contract_types_are_lists(self, module_path: str) -> None:
        mod = importlib.import_module(module_path)
        c = mod.AGENT_CONTRACT
        assert isinstance(
            c["allowed_tools"], list
        ), f"{module_path}: allowed_tools must be list"
        assert isinstance(
            c["input_types"], list
        ), f"{module_path}: input_types must be list"
        assert isinstance(
            c["output_types"], list
        ), f"{module_path}: output_types must be list"
        assert isinstance(
            c["side_effects"], list
        ), f"{module_path}: side_effects must be list"
        assert isinstance(
            c["permissions"], list
        ), f"{module_path}: permissions must be list"
        assert isinstance(
            c["dependencies"], list
        ), f"{module_path}: dependencies must be list"

    @pytest.mark.parametrize("module_path", _DAY3_AGENTS)
    def test_contract_risk_level_valid(self, module_path: str) -> None:
        mod = importlib.import_module(module_path)
        risk = mod.AGENT_CONTRACT["risk_level"]
        assert risk in _VALID_RISK_LEVELS, f"{module_path}: invalid risk_level={risk!r}"

    @pytest.mark.parametrize("module_path", _DAY3_AGENTS)
    def test_contract_name_matches_module(self, module_path: str) -> None:
        mod = importlib.import_module(module_path)
        module_suffix = module_path.split(".")[-1]
        assert mod.AGENT_CONTRACT["name"] == module_suffix, (
            f"{module_path}: AGENT_CONTRACT['name']={mod.AGENT_CONTRACT['name']!r} "
            f"does not match module suffix {module_suffix!r}"
        )

    @pytest.mark.parametrize("module_path", _DAY3_AGENTS)
    def test_contract_description_non_empty(self, module_path: str) -> None:
        mod = importlib.import_module(module_path)
        desc = mod.AGENT_CONTRACT["description"]
        assert (
            isinstance(desc, str) and len(desc) > 10
        ), f"{module_path}: description too short or wrong type"


# ===========================================================================
# 2 · Capability registry registration (4 tests)
# ===========================================================================


class TestCapabilityRegistration:

    def test_all_day3_agents_registered(self) -> None:
        for mp in _DAY3_AGENTS:
            importlib.import_module(mp)
        from app.fleet.capability_registry import get_capability_registry

        registry = get_capability_registry()
        registered = registry.names()
        for mp in _DAY3_AGENTS:
            name = mp.split(".")[-1]
            assert name in registered, f"{name} not in capability_registry after import"

    def test_registry_entries_have_capabilities(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        registry = get_capability_registry()
        for mp in _DAY3_AGENTS:
            name = mp.split(".")[-1]
            cap = registry.get(name)
            assert cap is not None, f"{name} not in registry"
            assert len(cap.capabilities) > 0, f"{name}: capabilities list is empty"

    def test_registry_entries_risk_level(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        registry = get_capability_registry()
        for mp in _DAY3_AGENTS:
            name = mp.split(".")[-1]
            cap = registry.get(name)
            assert cap is not None
            assert (
                cap.risk_level in _VALID_RISK_LEVELS
            ), f"{name}: invalid risk_level={cap.risk_level!r}"

    def test_register_idempotent(self) -> None:
        for mp in _DAY3_AGENTS:
            mod = importlib.import_module(mp)
            mod._register()
            mod._register()
        from app.fleet.capability_registry import get_capability_registry

        registry = get_capability_registry()
        for mp in _DAY3_AGENTS:
            name = mp.split(".")[-1]
            assert (
                registry.get(name) is not None
            ), f"{name} missing after double register"


# ===========================================================================
# 3 · Fleet OS flag wiring (1 test per agent = 9 tests)
# ===========================================================================


class TestPerformanceReviewerFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.performance_reviewer.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.performance_reviewer.get_settings",
            return_value=_mock_settings(),
        ), patch(
            "app.agents.performance_reviewer.make_performance_reviewer_handlers",
            return_value={},
        ):
            from app.agents.performance_reviewer import run_performance_reviewer

            run_performance_reviewer(
                task_id=1, description="Check for slow SQL queries"
            )
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "performance_reviewer")


class TestStyleReviewerFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.style_reviewer.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.style_reviewer.get_settings", return_value=_mock_settings()
        ), patch(
            "app.agents.style_reviewer.make_style_reviewer_handlers", return_value={}
        ):
            from app.agents.style_reviewer import run_style_reviewer

            run_style_reviewer(task_id=2, description="Enforce PEP8 on backend")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "style_reviewer")


class TestSprintPlannerFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.sprint_planner.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.sprint_planner.get_settings", return_value=_mock_settings()
        ), patch(
            "app.agents.sprint_planner.make_sprint_planner_handlers", return_value={}
        ):
            from app.agents.sprint_planner import run_sprint_planner

            run_sprint_planner(task_id=3, description="Plan auth feature sprint")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "sprint_planner")


class TestBusinessAnalystFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.business_analyst.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.business_analyst.get_settings", return_value=_mock_settings()
        ), patch(
            "app.agents.business_analyst.make_business_analyst_handlers",
            return_value={},
        ):
            from app.agents.business_analyst import run_business_analyst

            run_business_analyst(
                task_id=4, description="Extract user stories for dashboard"
            )
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "business_analyst")


class TestMigrationAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.migration_agent.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.migration_agent.get_settings", return_value=_mock_settings()
        ), patch(
            "app.agents.migration_agent.make_migration_agent_handlers", return_value={}
        ):
            from app.agents.migration_agent import run_migration_agent

            run_migration_agent(task_id=5, description="Add user_roles table")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "migration_agent")


class TestSchemaAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.schema_agent.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.schema_agent.get_settings", return_value=_mock_settings()
        ), patch(
            "app.agents.schema_agent.make_schema_agent_handlers", return_value={}
        ):
            from app.agents.schema_agent import run_schema_agent

            run_schema_agent(task_id=6, description="Review events table normalization")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "schema_agent")


class TestAiEngineerFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.ai_engineer.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.ai_engineer.get_settings", return_value=_mock_settings()
        ), patch(
            "app.agents.ai_engineer.make_ai_engineer_handlers", return_value={}
        ):
            from app.agents.ai_engineer import run_ai_engineer

            run_ai_engineer(task_id=7, description="Add embedding pipeline for search")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "ai_engineer")


class TestCleanupAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.cleanup_agent.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.cleanup_agent.get_settings", return_value=_mock_settings()
        ), patch(
            "app.agents.cleanup_agent.make_cleanup_agent_handlers", return_value={}
        ):
            from app.agents.cleanup_agent import run_cleanup_agent

            run_cleanup_agent(task_id=8, description="Remove dead code in agents/")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "cleanup_agent")


class TestTechDebtAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.tech_debt_agent.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.tech_debt_agent.get_settings", return_value=_mock_settings()
        ), patch(
            "app.agents.tech_debt_agent.make_tech_debt_agent_handlers", return_value={}
        ):
            from app.agents.tech_debt_agent import run_tech_debt_agent

            run_tech_debt_agent(task_id=9, description="Full tech debt audit")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "tech_debt_agent")


# ===========================================================================
# 4 · FleetManager capability query (1 test per agent = 9 tests)
# ===========================================================================


class TestFleetManagerCapabilityQuery:

    def _get_by_capability(self, cap: str) -> list[str]:
        from app.fleet.capability_registry import get_capability_registry

        return [
            e.name for e in get_capability_registry().all() if cap in e.capabilities
        ]

    def test_performance_reviewer_selectable_by_capability(self) -> None:
        import app.agents.performance_reviewer  # noqa: F401

        names = self._get_by_capability("performance_review")
        assert "performance_reviewer" in names

    def test_style_reviewer_selectable_by_capability(self) -> None:
        import app.agents.style_reviewer  # noqa: F401

        names = self._get_by_capability("style_review")
        assert "style_reviewer" in names

    def test_sprint_planner_selectable_by_capability(self) -> None:
        import app.agents.sprint_planner  # noqa: F401

        names = self._get_by_capability("sprint_planning")
        assert "sprint_planner" in names

    def test_business_analyst_selectable_by_capability(self) -> None:
        import app.agents.business_analyst  # noqa: F401

        names = self._get_by_capability("business_analysis")
        assert "business_analyst" in names

    def test_migration_agent_selectable_by_capability(self) -> None:
        import app.agents.migration_agent  # noqa: F401

        names = self._get_by_capability("database_migration")
        assert "migration_agent" in names

    def test_schema_agent_selectable_by_capability(self) -> None:
        import app.agents.schema_agent  # noqa: F401

        names = self._get_by_capability("schema_design")
        assert "schema_agent" in names

    def test_ai_engineer_selectable_by_capability(self) -> None:
        import app.agents.ai_engineer  # noqa: F401

        names = self._get_by_capability("ai_ml_engineering")
        assert "ai_engineer" in names

    def test_cleanup_agent_selectable_by_capability(self) -> None:
        import app.agents.cleanup_agent  # noqa: F401

        names = self._get_by_capability("code_cleanup")
        assert "cleanup_agent" in names

    def test_tech_debt_agent_selectable_by_capability(self) -> None:
        import app.agents.tech_debt_agent  # noqa: F401

        names = self._get_by_capability("technical_debt_analysis")
        assert "tech_debt_agent" in names


# ===========================================================================
# 5 · VerificationConfig enforce_in_result non-empty (9 tests)
# ===========================================================================


class TestVerificationConfigEnforce:

    @pytest.mark.parametrize("module_path", _DAY3_AGENTS)
    def test_enforce_in_result_non_empty(self, module_path: str) -> None:
        mod = importlib.import_module(module_path)
        cfg = mod._VERIFICATION_CFG
        assert len(cfg.enforce_in_result) > 0, (
            f"{module_path}: enforce_in_result is empty — "
            "agent can submit without verification being checked"
        )
