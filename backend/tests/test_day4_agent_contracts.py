"""Day 4 Agent Contract Tests — 8 agents.

Covers:
  - AGENT_CONTRACT structure (5 tests × 8 agents = 40)
  - Capability registry registration (4 tests)
  - Fleet OS flag wiring per task agent (7 tests — manager excluded, it's an orchestrator)
  - FleetManager capability query (8 tests)
  - VerificationConfig enforce_in_result non-empty (7 tests — manager excluded)

Total: 66 tests
"""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Agent lists
# ---------------------------------------------------------------------------
_DAY4_TASK_AGENTS = [
    "app.agents.release_notes_agent",
    "app.agents.evaluation_agent",
    "app.agents.rag_engineer_agent",
    "app.agents.changelog_agent",
    "app.agents.user_story_generator",
    "app.agents.security_architect",
    "app.agents.database_architect",
]

_DAY4_ALL_AGENTS = _DAY4_TASK_AGENTS + ["app.agents.manager"]

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
# Final state mock for task agents
# ---------------------------------------------------------------------------
_FINAL_STATE: dict[str, Any] = {
    "messages": [],
    "verification": {
        "git_log_read": True,
        "eval_run": True,
        "codebase_read": True,
        "changelog_written": True,
        "stories_written": True,
        "schema_read": True,
        "code_written": True,
    },
    "result": {
        "summary": "test",
        "version": "v1.0.0",
        "content": "# Release notes",
        "highlights": ["feature A"],
        "breaking_changes": [],
        "overall_score": 0.9,
        "pass_count": 9,
        "fail_count": 1,
        "cases": [],
        "vector_store": "pgvector",
        "embedding_model": "voyage-code-2",
        "retrieval_strategy": "top-k",
        "chunking_strategy": "recursive",
        "implementation_notes": [],
        "files_written": [],
        "sections": {"added": 2, "fixed": 1},
        "file_path": "CHANGELOG.md",
        "feature": "login",
        "stories": [],
        "threats": [],
        "overall_risk": "low",
        "owasp_findings": [],
        "recommendations": [],
        "tables": [],
        "indexes": [],
        "migration_notes": [],
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
# 1 · AGENT_CONTRACT structure (5 × 8 = 40 tests)
# ===========================================================================


class TestAgentContractFormat:

    @pytest.mark.parametrize("module_path", _DAY4_ALL_AGENTS)
    def test_contract_has_required_keys(self, module_path: str) -> None:
        mod = importlib.import_module(module_path)
        missing = _REQUIRED_CONTRACT_KEYS - set(mod.AGENT_CONTRACT.keys())
        assert not missing, f"{module_path}: missing keys: {missing}"

    @pytest.mark.parametrize("module_path", _DAY4_ALL_AGENTS)
    def test_contract_types_are_lists(self, module_path: str) -> None:
        c = importlib.import_module(module_path).AGENT_CONTRACT
        for field in [
            "allowed_tools",
            "input_types",
            "output_types",
            "side_effects",
            "permissions",
            "dependencies",
        ]:
            assert isinstance(c[field], list), f"{module_path}: {field} must be list"

    @pytest.mark.parametrize("module_path", _DAY4_ALL_AGENTS)
    def test_contract_risk_level_valid(self, module_path: str) -> None:
        rl = importlib.import_module(module_path).AGENT_CONTRACT["risk_level"]
        assert rl in _VALID_RISK_LEVELS, f"{module_path}: invalid risk_level={rl!r}"

    @pytest.mark.parametrize("module_path", _DAY4_ALL_AGENTS)
    def test_contract_name_matches_module(self, module_path: str) -> None:
        mod = importlib.import_module(module_path)
        suffix = module_path.split(".")[-1]
        assert (
            mod.AGENT_CONTRACT["name"] == suffix
        ), f"{module_path}: name={mod.AGENT_CONTRACT['name']!r} != {suffix!r}"

    @pytest.mark.parametrize("module_path", _DAY4_ALL_AGENTS)
    def test_contract_description_non_empty(self, module_path: str) -> None:
        desc = importlib.import_module(module_path).AGENT_CONTRACT["description"]
        assert isinstance(desc, str) and len(desc) > 10


# ===========================================================================
# 2 · Capability registry (4 tests)
# ===========================================================================


class TestCapabilityRegistration:

    def test_all_day4_agents_registered(self) -> None:
        for mp in _DAY4_ALL_AGENTS:
            importlib.import_module(mp)
        from app.fleet.capability_registry import get_capability_registry

        reg = get_capability_registry()
        for mp in _DAY4_ALL_AGENTS:
            name = mp.split(".")[-1]
            assert name in reg.names(), f"{name} not in registry"

    def test_task_agents_have_non_empty_capabilities(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        reg = get_capability_registry()
        for mp in _DAY4_TASK_AGENTS:
            name = mp.split(".")[-1]
            cap = reg.get(name)
            assert (
                cap is not None and len(cap.capabilities) > 0
            ), f"{name}: capabilities empty"

    def test_registry_entries_valid_risk_level(self) -> None:
        from app.fleet.capability_registry import get_capability_registry

        reg = get_capability_registry()
        for mp in _DAY4_ALL_AGENTS:
            name = mp.split(".")[-1]
            cap = reg.get(name)
            assert cap is not None and cap.risk_level in _VALID_RISK_LEVELS

    def test_register_idempotent(self) -> None:
        for mp in _DAY4_ALL_AGENTS:
            mod = importlib.import_module(mp)
            mod._register()
            mod._register()
        from app.fleet.capability_registry import get_capability_registry

        reg = get_capability_registry()
        for mp in _DAY4_ALL_AGENTS:
            name = mp.split(".")[-1]
            assert reg.get(name) is not None


# ===========================================================================
# 3 · Fleet OS flags (7 task agents — manager is orchestrator, excluded)
# ===========================================================================


class TestReleaseNotesAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.release_notes_agent.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.release_notes_agent.get_settings", return_value=_mock_settings()
        ), patch(
            "app.agents.release_notes_agent.make_release_notes_handlers",
            return_value={"_release_notes_result": {}},
        ):
            from app.agents.release_notes_agent import run_release_notes_agent

            run_release_notes_agent(
                task_id=1, description="Generate v1.2.0 release notes"
            )
            _assert_all_flags(mock_run.call_args_list[0][1], "release_notes_agent")


class TestEvaluationAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.evaluation_agent.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.evaluation_agent.get_settings", return_value=_mock_settings()
        ), patch(
            "app.agents.evaluation_agent.make_evaluation_handlers",
            return_value={"_eval_result": {}},
        ):
            from app.agents.evaluation_agent import run_evaluation_agent

            run_evaluation_agent(task_id=2, description="Evaluate agent output quality")
            _assert_all_flags(mock_run.call_args_list[0][1], "evaluation_agent")


class TestRagEngineerAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.rag_engineer_agent.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.rag_engineer_agent.get_settings", return_value=_mock_settings()
        ), patch(
            "app.agents.rag_engineer_agent.make_rag_engineer_handlers",
            return_value={"_rag_result": {}},
        ):
            from app.agents.rag_engineer_agent import run_rag_engineer_agent

            run_rag_engineer_agent(
                task_id=3, description="Design RAG pipeline for code search"
            )
            _assert_all_flags(mock_run.call_args_list[0][1], "rag_engineer_agent")


class TestChangelogAgentFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.changelog_agent.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.changelog_agent.get_settings", return_value=_mock_settings()
        ), patch(
            "app.agents.changelog_agent.make_changelog_handlers",
            return_value={"_changelog_result": {}},
        ):
            from app.agents.changelog_agent import run_changelog_agent

            run_changelog_agent(
                task_id=4, description="Generate CHANGELOG.md for v2.0.0"
            )
            _assert_all_flags(mock_run.call_args_list[0][1], "changelog_agent")


class TestUserStoryGeneratorFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.user_story_generator.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.user_story_generator.get_settings",
            return_value=_mock_settings(),
        ), patch(
            "app.agents.user_story_generator.make_user_story_handlers",
            return_value={"_user_story_result": {}},
        ):
            from app.agents.user_story_generator import run_user_story_generator

            run_user_story_generator(
                task_id=5, description="Write user stories for login feature"
            )
            _assert_all_flags(mock_run.call_args_list[0][1], "user_story_generator")


class TestSecurityArchitectFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.security_architect.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.security_architect.get_settings", return_value=_mock_settings()
        ), patch(
            "app.agents.security_architect.make_security_architect_handlers",
            return_value={"_security_result": {}},
        ):
            from app.agents.security_architect import run_security_architect

            run_security_architect(
                task_id=6, description="STRIDE threat model for auth module"
            )
            _assert_all_flags(mock_run.call_args_list[0][1], "security_architect")


class TestDatabaseArchitectFlags:
    def test_fleet_flags(self) -> None:
        with patch(
            "app.agents.database_architect.run_agent_graph", return_value=_FINAL_STATE
        ) as mock_run, patch(
            "app.agents.database_architect.get_settings", return_value=_mock_settings()
        ), patch(
            "app.agents.database_architect.make_database_architect_handlers",
            return_value={"_db_result": {}},
        ):
            from app.agents.database_architect import run_database_architect

            run_database_architect(
                task_id=7, description="Review schema normalization for events table"
            )
            _assert_all_flags(mock_run.call_args_list[0][1], "database_architect")


# ===========================================================================
# 4 · FleetManager capability query (8 tests)
# ===========================================================================


class TestFleetManagerCapabilityQuery:

    def _get_by_cap(self, cap: str) -> list[str]:
        from app.fleet.capability_registry import get_capability_registry

        return [
            e.name for e in get_capability_registry().all() if cap in e.capabilities
        ]

    def test_release_notes_agent_selectable(self) -> None:
        import app.agents.release_notes_agent  # noqa: F401

        assert "release_notes_agent" in self._get_by_cap("release_notes_generation")

    def test_evaluation_agent_selectable(self) -> None:
        import app.agents.evaluation_agent  # noqa: F401

        assert "evaluation_agent" in self._get_by_cap("llm_evaluation")

    def test_rag_engineer_agent_selectable(self) -> None:
        import app.agents.rag_engineer_agent  # noqa: F401

        assert "rag_engineer_agent" in self._get_by_cap("rag_pipeline_design")

    def test_changelog_agent_selectable(self) -> None:
        import app.agents.changelog_agent  # noqa: F401

        assert "changelog_agent" in self._get_by_cap("changelog_generation")

    def test_user_story_generator_selectable(self) -> None:
        import app.agents.user_story_generator  # noqa: F401

        assert "user_story_generator" in self._get_by_cap("user_story_generation")

    def test_security_architect_selectable(self) -> None:
        import app.agents.security_architect  # noqa: F401

        assert "security_architect" in self._get_by_cap("threat_modelling")

    def test_database_architect_selectable(self) -> None:
        import app.agents.database_architect  # noqa: F401

        assert "database_architect" in self._get_by_cap("database_schema_design")

    def test_manager_selectable(self) -> None:
        import app.agents.manager  # noqa: F401

        assert "manager" in self._get_by_cap("task_orchestration")


# ===========================================================================
# 5 · VerificationConfig enforce_in_result non-empty (7 task agents)
# ===========================================================================


class TestVerificationConfigEnforce:

    @pytest.mark.parametrize("module_path", _DAY4_TASK_AGENTS)
    def test_enforce_in_result_non_empty(self, module_path: str) -> None:
        mod = importlib.import_module(module_path)
        cfg = mod._VERIFICATION_CFG
        assert (
            len(cfg.enforce_in_result) > 0
        ), f"{module_path}: enforce_in_result is empty — agent can submit without verification"
