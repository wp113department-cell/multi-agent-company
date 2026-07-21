"""
Day 2 — AGENT_CONTRACT for 11 base_graph agents.
=================================================
Verifies:
  1. Every agent has a well-formed AGENT_CONTRACT (new format).
  2. Every agent self-registers in capability_registry + agent_registry at import time.
  3. Fleet OS flags (enable_planning/memory/reflection/lesson=True + task_description +
     repo_path + model_haiku) are passed through to run_agent_graph.
  4. Capability queries succeed (fleet_manager can select each agent by capability).

Tests use mocked LLM — no network, no DB, no API key required.
"""
from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Required AGENT_CONTRACT fields (new format — all 10 keys)
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = frozenset({
    "name", "description", "allowed_tools", "input_types", "output_types",
    "side_effects", "permissions", "risk_level", "expected_verification", "dependencies",
})

_ALLOWED_RISK_LEVELS = {"low", "medium", "high"}

# ---------------------------------------------------------------------------
# Minimal mock final state for run_agent_graph
# ---------------------------------------------------------------------------

_FINAL_STATE: dict[str, Any] = {
    "messages": [{"role": "assistant", "content": [{"type": "text", "text": "done"}]}],
    "submitted": True,
    "result": {
        "fix_summary": "ok", "root_cause": "ok", "files_changed": [],
        "findings": [], "summary": "ok", "structure_summary": "1 module",
        "risks": [], "recommendations": [], "blast_radius": "low",
        "query_or_migration": "SELECT 1", "explain_plan_summary": "ok",
        "verified_against_schema": True, "is_destructive": False, "warnings": [],
        "files_written": [], "files_changed": [], "status": "healthy",  # noqa: F601
        "metrics": {}, "issues": [], "dependencies": [],
        "content_markdown": "# README", "verified_commands": [], "sections": [],
        "endpoints": [], "spec_drift": [],
    },
    "requires_human_approval": False,
    "verification": {
        "tests_passed": True, "diff_checked": True, "scan_ran": True,
        "import_graph_ran": True, "schema_inspected": True, "build_ran": True,
        "lint_ran": True, "manifest_read": True, "metrics_collected": True,
        "files_read": True, "routes_found": True,
    },
    "tokens_in": 10,
    "tokens_out": 5,
    "turns": 1,
    "trace_id": "test-trace",
    "status": "done",
}


def _mock_settings() -> MagicMock:
    s = MagicMock()
    s.model_planner = "haiku-test"
    s.model_coder = "sonnet-test"
    s.model_router = "haiku-test"
    s.target_repo_path = "/tmp/test-repo"
    return s


def _assert_all_flags(kwargs: dict[str, Any], agent_name: str) -> None:
    for flag in ("enable_planning", "enable_memory", "enable_reflection", "enable_lesson"):
        assert kwargs.get(flag) is True, f"{agent_name}: {flag} must be True"
    assert kwargs.get("task_description"), f"{agent_name}: task_description must be non-empty"
    assert kwargs.get("repo_path"), f"{agent_name}: repo_path must be set"
    assert kwargs.get("model_haiku"), f"{agent_name}: model_haiku must be set"


# ---------------------------------------------------------------------------
# CONTRACT FORMAT TESTS — verify all 11 AGENT_CONTRACT dicts
# ---------------------------------------------------------------------------

_DAY2_AGENTS = [
    "app.agents.bug_fix",
    "app.agents.security_reviewer",
    "app.agents.architecture_reviewer",
    "app.agents.sql_agent",
    "app.agents.docker_agent",
    "app.agents.cicd_agent",
    "app.agents.refactor_agent",
    "app.agents.readme_agent",
    "app.agents.api_docs_agent",
    "app.agents.dependency_agent",
    "app.agents.monitoring_agent",
]


class TestAgentContractFormat:
    """Every Day 2 agent must have a well-formed AGENT_CONTRACT."""

    @pytest.mark.parametrize("module_path", _DAY2_AGENTS)
    def test_contract_has_required_keys(self, module_path: str) -> None:
        mod: ModuleType = importlib.import_module(module_path)
        contract: dict[str, Any] = getattr(mod, "AGENT_CONTRACT")
        missing = _REQUIRED_KEYS - set(contract.keys())
        assert not missing, f"{module_path}: AGENT_CONTRACT missing keys: {missing}"

    @pytest.mark.parametrize("module_path", _DAY2_AGENTS)
    def test_contract_types_are_lists(self, module_path: str) -> None:
        mod: ModuleType = importlib.import_module(module_path)
        contract: dict[str, Any] = getattr(mod, "AGENT_CONTRACT")
        assert isinstance(contract["input_types"], list), f"{module_path}: input_types must be list"
        assert isinstance(contract["output_types"], list), f"{module_path}: output_types must be list"
        assert isinstance(contract["allowed_tools"], list), f"{module_path}: allowed_tools must be list"
        assert isinstance(contract["dependencies"], list), f"{module_path}: dependencies must be list"

    @pytest.mark.parametrize("module_path", _DAY2_AGENTS)
    def test_contract_risk_level_valid(self, module_path: str) -> None:
        mod: ModuleType = importlib.import_module(module_path)
        contract: dict[str, Any] = getattr(mod, "AGENT_CONTRACT")
        assert contract["risk_level"] in _ALLOWED_RISK_LEVELS, (
            f"{module_path}: risk_level '{contract['risk_level']}' not in {_ALLOWED_RISK_LEVELS}"
        )

    @pytest.mark.parametrize("module_path", _DAY2_AGENTS)
    def test_contract_name_matches_module(self, module_path: str) -> None:
        mod: ModuleType = importlib.import_module(module_path)
        contract: dict[str, Any] = getattr(mod, "AGENT_CONTRACT")
        expected_name = module_path.split(".")[-1]
        assert contract["name"] == expected_name, (
            f"{module_path}: AGENT_CONTRACT name '{contract['name']}' != '{expected_name}'"
        )

    @pytest.mark.parametrize("module_path", _DAY2_AGENTS)
    def test_contract_description_non_empty(self, module_path: str) -> None:
        mod: ModuleType = importlib.import_module(module_path)
        contract: dict[str, Any] = getattr(mod, "AGENT_CONTRACT")
        assert contract["description"].strip(), f"{module_path}: AGENT_CONTRACT description must be non-empty"


# ---------------------------------------------------------------------------
# CAPABILITY REGISTRY TESTS — all 11 self-register at import time
# ---------------------------------------------------------------------------

class TestCapabilityRegistration:
    """All Day 2 agents must appear in capability_registry after import."""

    def test_all_day2_agents_registered(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        registry = get_capability_registry()
        for module_path in _DAY2_AGENTS:
            importlib.import_module(module_path)
            name = module_path.split(".")[-1]
            entry = registry.get(name)
            assert entry is not None, f"{name} not found in capability_registry after import"

    def test_registry_entries_have_capabilities(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        registry = get_capability_registry()
        for module_path in _DAY2_AGENTS:
            importlib.import_module(module_path)
            name = module_path.split(".")[-1]
            entry = registry.get(name)
            assert entry is not None
            assert entry.capabilities, f"{name}: capabilities list must be non-empty"

    def test_registry_entries_risk_level(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        registry = get_capability_registry()
        for module_path in _DAY2_AGENTS:
            importlib.import_module(module_path)
            name = module_path.split(".")[-1]
            entry = registry.get(name)
            assert entry is not None
            assert entry.risk_level in _ALLOWED_RISK_LEVELS, (
                f"{name}: registry risk_level '{entry.risk_level}' is invalid"
            )

    def test_register_idempotent(self) -> None:
        from app.fleet.capability_registry import get_capability_registry
        from app.agents import bug_fix
        bug_fix._register()
        bug_fix._register()
        entry = get_capability_registry().get("bug_fix")
        assert entry is not None


# ---------------------------------------------------------------------------
# FLEET OS FLAGS TESTS — each agent passes all 4 flags to run_agent_graph
# ---------------------------------------------------------------------------

class TestBugFixFlags:
    def test_fleet_flags(self) -> None:
        with patch("app.agents.bug_fix.run_agent_graph", return_value=_FINAL_STATE) as mock_run, \
             patch("app.agents.bug_fix.get_settings", return_value=_mock_settings()), \
             patch("app.agents.bug_fix.make_bug_fix_handlers", return_value={}):
            from app.agents.bug_fix import run_bug_fix
            run_bug_fix(task_id=1, error_description="NullPointerException in login")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "bug_fix")


class TestSecurityReviewerFlags:
    def test_fleet_flags(self) -> None:
        with patch("app.agents.security_reviewer.run_agent_graph", return_value=_FINAL_STATE) as mock_run, \
             patch("app.agents.security_reviewer.get_settings", return_value=_mock_settings()), \
             patch("app.agents.security_reviewer.make_security_reviewer_handlers", return_value={}):
            from app.agents.security_reviewer import run_security_review
            run_security_review(task_id=2, focus="auth check")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "security_reviewer")


class TestArchitectureReviewerFlags:
    def test_fleet_flags(self) -> None:
        with patch("app.agents.architecture_reviewer.run_agent_graph", return_value=_FINAL_STATE) as mock_run, \
             patch("app.agents.architecture_reviewer.get_settings", return_value=_mock_settings()), \
             patch("app.agents.architecture_reviewer.make_arch_reviewer_handlers", return_value={}):
            from app.agents.architecture_reviewer import run_arch_review
            run_arch_review(task_id=3, focus="full")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "architecture_reviewer")


class TestSQLAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch("app.agents.sql_agent.run_agent_graph", return_value=_FINAL_STATE) as mock_run, \
             patch("app.agents.sql_agent.get_settings", return_value=_mock_settings()), \
             patch("app.agents.sql_agent.make_sql_agent_handlers", return_value={}):
            from app.agents.sql_agent import run_sql_agent
            run_sql_agent(task_id=4, task_description="Add index on user_id")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "sql_agent")


class TestDockerAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch("app.agents.docker_agent.run_agent_graph", return_value=_FINAL_STATE) as mock_run, \
             patch("app.agents.docker_agent.get_settings", return_value=_mock_settings()), \
             patch("app.agents.docker_agent.make_docker_agent_handlers", return_value={}):
            from app.agents.docker_agent import run_docker_agent
            run_docker_agent(task_id=5, task_description="Slim the image")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "docker_agent")


class TestCICDAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch("app.agents.cicd_agent.run_agent_graph", return_value=_FINAL_STATE) as mock_run, \
             patch("app.agents.cicd_agent.get_settings", return_value=_mock_settings()), \
             patch("app.agents.cicd_agent.make_cicd_agent_handlers", return_value={}):
            from app.agents.cicd_agent import run_cicd_agent
            run_cicd_agent(task_id=6, task_description="Add deploy step")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "cicd_agent")


class TestRefactorAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch("app.agents.refactor_agent.run_agent_graph", return_value=_FINAL_STATE) as mock_run, \
             patch("app.agents.refactor_agent.get_settings", return_value=_mock_settings()), \
             patch("app.agents.refactor_agent.make_refactor_agent_handlers", return_value={}):
            from app.agents.refactor_agent import run_refactor_agent
            run_refactor_agent(task_id=7, refactor_instructions="Extract helper function")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "refactor_agent")


class TestReadmeAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch("app.agents.readme_agent.run_agent_graph", return_value=_FINAL_STATE) as mock_run, \
             patch("app.agents.readme_agent.get_settings", return_value=_mock_settings()), \
             patch("app.agents.readme_agent.make_readme_agent_handlers", return_value={}):
            from app.agents.readme_agent import run_readme_agent
            run_readme_agent(task_id=8, doc_request="Write README for backend")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "readme_agent")


class TestAPIDocsAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch("app.agents.api_docs_agent.run_agent_graph", return_value=_FINAL_STATE) as mock_run, \
             patch("app.agents.api_docs_agent.get_settings", return_value=_mock_settings()), \
             patch("app.agents.api_docs_agent.make_api_docs_agent_handlers", return_value={}):
            from app.agents.api_docs_agent import run_api_docs_agent
            run_api_docs_agent(task_id=9, doc_request="Document all /api routes")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "api_docs_agent")


class TestDependencyAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch("app.agents.dependency_agent.run_agent_graph", return_value=_FINAL_STATE) as mock_run, \
             patch("app.agents.dependency_agent.get_settings", return_value=_mock_settings()), \
             patch("app.agents.dependency_agent.make_dependency_agent_handlers", return_value={}):
            from app.agents.dependency_agent import run_dependency_agent
            run_dependency_agent(task_id=10, task_description="Check for outdated packages")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "dependency_agent")


class TestMonitoringAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch("app.agents.monitoring_agent.run_agent_graph", return_value=_FINAL_STATE) as mock_run, \
             patch("app.agents.monitoring_agent.get_settings", return_value=_mock_settings()), \
             patch("app.agents.monitoring_agent.make_monitoring_agent_handlers", return_value={}):
            from app.agents.monitoring_agent import run_monitoring_agent
            run_monitoring_agent(task_id=11, task_description="Full health check")
            kwargs = mock_run.call_args_list[0][1]
            _assert_all_flags(kwargs, "monitoring_agent")


# ---------------------------------------------------------------------------
# FLEET MANAGER SELECTION — capability registry query by capability tag
# ---------------------------------------------------------------------------

class TestFleetManagerCapabilityQuery:
    """Fleet manager can find each Day 2 agent by its declared capability."""

    def _get_by_capability(self, cap: str) -> list[str]:
        from app.fleet.capability_registry import get_capability_registry
        registry = get_capability_registry()
        return [e.name for e in registry.all() if cap in e.capabilities]

    def test_bug_fix_selectable_by_capability(self) -> None:
        import app.agents.bug_fix  # noqa: F401 — ensure registered
        names = self._get_by_capability("bug_fixing")
        assert "bug_fix" in names

    def test_security_reviewer_selectable_by_capability(self) -> None:
        import app.agents.security_reviewer  # noqa: F401
        names = self._get_by_capability("security_review")
        assert "security_reviewer" in names

    def test_architecture_reviewer_selectable_by_capability(self) -> None:
        import app.agents.architecture_reviewer  # noqa: F401
        names = self._get_by_capability("architecture_review")
        assert "architecture_reviewer" in names

    def test_sql_agent_selectable_by_capability(self) -> None:
        import app.agents.sql_agent  # noqa: F401
        names = self._get_by_capability("sql_management")
        assert "sql_agent" in names

    def test_docker_agent_selectable_by_capability(self) -> None:
        import app.agents.docker_agent  # noqa: F401
        names = self._get_by_capability("docker_management")
        assert "docker_agent" in names

    def test_cicd_agent_selectable_by_capability(self) -> None:
        import app.agents.cicd_agent  # noqa: F401
        names = self._get_by_capability("cicd_management")
        assert "cicd_agent" in names

    def test_refactor_agent_selectable_by_capability(self) -> None:
        import app.agents.refactor_agent  # noqa: F401
        names = self._get_by_capability("refactoring")
        assert "refactor_agent" in names

    def test_readme_agent_selectable_by_capability(self) -> None:
        import app.agents.readme_agent  # noqa: F401
        names = self._get_by_capability("documentation_writing")
        assert "readme_agent" in names

    def test_api_docs_agent_selectable_by_capability(self) -> None:
        import app.agents.api_docs_agent  # noqa: F401
        names = self._get_by_capability("api_documentation")
        assert "api_docs_agent" in names

    def test_dependency_agent_selectable_by_capability(self) -> None:
        import app.agents.dependency_agent  # noqa: F401
        names = self._get_by_capability("dependency_management")
        assert "dependency_agent" in names

    def test_monitoring_agent_selectable_by_capability(self) -> None:
        import app.agents.monitoring_agent  # noqa: F401
        names = self._get_by_capability("infrastructure_monitoring")
        assert "monitoring_agent" in names
