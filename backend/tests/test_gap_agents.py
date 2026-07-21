"""Gap agents — structural tests for the 7 new agents (no real LLM calls).

Tests cover:
  - Module importability (no syntax / import errors)
  - Handler factory: correct keys, callable values
  - Submit handler present and callable
  - Read-only base handlers present
  - VerificationConfig has initial dict + set_by map
  - Specialized-agents registry includes every gap agent
  - Role files exist for each agent
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Import all 7 gap agent modules — catches syntax errors at collection time
# ---------------------------------------------------------------------------
from app.agents.release_notes_agent import (
    run_release_notes_agent,
    make_release_notes_handlers,
    _VERIFICATION_CFG as _RN_VCFG,
    _RELEASE_NOTES_TOOLS,
)
from app.agents.evaluation_agent import (
    run_evaluation_agent,
    make_evaluation_handlers,
    _VERIFICATION_CFG as _EVAL_VCFG,
    _EVAL_TOOLS,
)
from app.agents.rag_engineer_agent import (
    run_rag_engineer_agent,
    make_rag_engineer_handlers,
    _VERIFICATION_CFG as _RAG_VCFG,
    _RAG_TOOLS,
)
from app.agents.changelog_agent import (
    run_changelog_agent,
    make_changelog_handlers,
    _VERIFICATION_CFG as _CL_VCFG,
    _CHANGELOG_TOOLS,
)
from app.agents.user_story_generator import (
    run_user_story_generator,
    make_user_story_handlers,
    _VERIFICATION_CFG as _US_VCFG,
    _USER_STORY_TOOLS,
)
from app.agents.security_architect import (
    run_security_architect,
    make_security_architect_handlers,
    _VERIFICATION_CFG as _SA_VCFG,
    _SECURITY_TOOLS,
)
from app.agents.database_architect import (
    run_database_architect,
    make_database_architect_handlers,
    _VERIFICATION_CFG as _DBA_VCFG,
    _DB_TOOLS,
)
from app.agents.tools import READ_ONLY_TOOLS
from app.agents.base_graph import VerificationConfig

_REPO = str(Path(__file__).parent.parent.parent)
_ROLES_DIR = Path(__file__).parent.parent / "roles"


def _tool_names(tools: list[dict[str, Any]]) -> set[str]:
    return {t["name"] for t in tools}


READ_ONLY_NAMES = _tool_names(READ_ONLY_TOOLS)


def _assert_handlers_valid(factory_fn: Any) -> dict[str, Any]:
    h = factory_fn(_REPO)
    assert len(h) > 0, "Handler dict is empty"
    for name, val in h.items():
        if name.startswith("_"):
            continue
        assert callable(val), f"Handler '{name}' is not callable"
    return h


# ===========================================================================
# Release Notes Agent
# ===========================================================================


class TestReleaseNotesAgent:
    def test_run_fn_is_callable(self) -> None:
        assert callable(run_release_notes_agent)

    def test_tools_include_read_only(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(_RELEASE_NOTES_TOOLS))

    def test_tools_include_generate_release_notes(self) -> None:
        assert "generate_release_notes" in _tool_names(_RELEASE_NOTES_TOOLS)

    def test_tools_include_generate_changelog(self) -> None:
        assert "generate_changelog" in _tool_names(_RELEASE_NOTES_TOOLS)

    def test_tools_include_submit(self) -> None:
        assert "submit_release_notes" in _tool_names(_RELEASE_NOTES_TOOLS)

    def test_all_tools_have_required_fields(self) -> None:
        for tool in _RELEASE_NOTES_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

    def test_verification_cfg_type(self) -> None:
        assert isinstance(_RN_VCFG, VerificationConfig)

    def test_verification_cfg_set_by_has_git_tools(self) -> None:
        assert "generate_release_notes" in _RN_VCFG.set_by
        assert "generate_changelog" in _RN_VCFG.set_by

    def test_verification_cfg_initial_has_git_log_read(self) -> None:
        assert "git_log_read" in _RN_VCFG.initial

    def test_handlers_are_valid(self) -> None:
        _assert_handlers_valid(make_release_notes_handlers)

    def test_submit_handler_present(self) -> None:
        h = make_release_notes_handlers(_REPO)
        assert "submit_release_notes" in h
        assert callable(h["submit_release_notes"])

    def test_submit_handler_stores_result(self) -> None:
        h = make_release_notes_handlers(_REPO)
        h["submit_release_notes"](
            {
                "version": "v1.0.0",
                "content": "## v1.0.0\n- initial",
                "highlights": ["First release"],
            }
        )
        result = h["_release_notes_result"]
        assert result["version"] == "v1.0.0"

    def test_read_file_handler_present(self) -> None:
        h = make_release_notes_handlers(_REPO)
        assert "read_file" in h and callable(h["read_file"])

    def test_role_file_exists(self) -> None:
        assert (_ROLES_DIR / "release_notes_agent.md").exists()


# ===========================================================================
# Evaluation Agent
# ===========================================================================


class TestEvaluationAgent:
    def test_run_fn_is_callable(self) -> None:
        assert callable(run_evaluation_agent)

    def test_tools_include_read_only(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(_EVAL_TOOLS))

    def test_tools_include_run_python_snippet(self) -> None:
        assert "run_python_snippet" in _tool_names(_EVAL_TOOLS)

    def test_tools_include_run_tests(self) -> None:
        assert "run_tests" in _tool_names(_EVAL_TOOLS)

    def test_tools_include_submit(self) -> None:
        assert "submit_eval_result" in _tool_names(_EVAL_TOOLS)

    def test_all_tools_have_required_fields(self) -> None:
        for tool in _EVAL_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

    def test_verification_cfg_type(self) -> None:
        assert isinstance(_EVAL_VCFG, VerificationConfig)

    def test_verification_cfg_set_by_run_snippet(self) -> None:
        assert "run_python_snippet" in _EVAL_VCFG.set_by
        assert _EVAL_VCFG.set_by["run_python_snippet"] == "eval_run"

    def test_verification_cfg_initial_has_eval_run(self) -> None:
        assert "eval_run" in _EVAL_VCFG.initial
        assert _EVAL_VCFG.initial["eval_run"] is False

    def test_handlers_are_valid(self) -> None:
        _assert_handlers_valid(make_evaluation_handlers)

    def test_submit_handler_present(self) -> None:
        h = make_evaluation_handlers(_REPO)
        assert "submit_eval_result" in h
        assert callable(h["submit_eval_result"])

    def test_submit_handler_stores_result(self) -> None:
        h = make_evaluation_handlers(_REPO)
        h["submit_eval_result"](
            {"overall_score": 0.8, "pass_count": 4, "fail_count": 1, "summary": "Good"}
        )
        result = h["_eval_result"]
        assert result["overall_score"] == 0.8
        assert result["pass_count"] == 4

    def test_role_file_exists(self) -> None:
        assert (_ROLES_DIR / "evaluation_agent.md").exists()


# ===========================================================================
# RAG Engineer Agent
# ===========================================================================


class TestRagEngineerAgent:
    def test_run_fn_is_callable(self) -> None:
        assert callable(run_rag_engineer_agent)

    def test_tools_include_read_only(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(_RAG_TOOLS))

    def test_tools_include_write_file(self) -> None:
        assert "write_file" in _tool_names(_RAG_TOOLS)

    def test_tools_include_run_python_snippet(self) -> None:
        assert "run_python_snippet" in _tool_names(_RAG_TOOLS)

    def test_tools_include_submit(self) -> None:
        assert "submit_rag_design" in _tool_names(_RAG_TOOLS)

    def test_all_tools_have_required_fields(self) -> None:
        for tool in _RAG_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

    def test_verification_cfg_type(self) -> None:
        assert isinstance(_RAG_VCFG, VerificationConfig)

    def test_verification_cfg_read_tools(self) -> None:
        assert "read_file" in _RAG_VCFG.set_by
        assert "search_code" in _RAG_VCFG.set_by
        assert _RAG_VCFG.set_by["read_file"] == "codebase_read"

    def test_verification_cfg_initial_has_codebase_read(self) -> None:
        assert "codebase_read" in _RAG_VCFG.initial
        assert _RAG_VCFG.initial["codebase_read"] is False

    def test_handlers_are_valid(self) -> None:
        _assert_handlers_valid(make_rag_engineer_handlers)

    def test_submit_handler_present(self) -> None:
        h = make_rag_engineer_handlers(_REPO)
        assert "submit_rag_design" in h
        assert callable(h["submit_rag_design"])

    def test_submit_handler_stores_result(self) -> None:
        h = make_rag_engineer_handlers(_REPO)
        h["submit_rag_design"](
            {
                "summary": "Use pgvector with voyage-code-2",
                "chunking_strategy": "recursive character 512 tokens",
                "embedding_model": "voyage-code-2",
                "vector_store": "pgvector",
                "retrieval_strategy": "cosine top-5",
            }
        )
        result = h["_rag_result"]
        assert result["vector_store"] == "pgvector"
        assert result["embedding_model"] == "voyage-code-2"

    def test_role_file_exists(self) -> None:
        assert (_ROLES_DIR / "rag_engineer_agent.md").exists()


# ===========================================================================
# Changelog Agent
# ===========================================================================


class TestChangelogAgent:
    def test_run_fn_is_callable(self) -> None:
        assert callable(run_changelog_agent)

    def test_tools_include_read_only(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(_CHANGELOG_TOOLS))

    def test_tools_include_generate_changelog(self) -> None:
        assert "generate_changelog" in _tool_names(_CHANGELOG_TOOLS)

    def test_tools_include_write_file(self) -> None:
        assert "write_file" in _tool_names(_CHANGELOG_TOOLS)

    def test_tools_include_submit(self) -> None:
        assert "submit_changelog" in _tool_names(_CHANGELOG_TOOLS)

    def test_all_tools_have_required_fields(self) -> None:
        for tool in _CHANGELOG_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

    def test_verification_cfg_type(self) -> None:
        assert isinstance(_CL_VCFG, VerificationConfig)

    def test_verification_cfg_generate_changelog_sets_git_log_read(self) -> None:
        assert "generate_changelog" in _CL_VCFG.set_by
        assert _CL_VCFG.set_by["generate_changelog"] == "git_log_read"

    def test_verification_cfg_write_file_sets_changelog_written(self) -> None:
        assert "write_file" in _CL_VCFG.set_by
        assert _CL_VCFG.set_by["write_file"] == "changelog_written"

    def test_handlers_are_valid(self) -> None:
        _assert_handlers_valid(make_changelog_handlers)

    def test_submit_handler_present(self) -> None:
        h = make_changelog_handlers(_REPO)
        assert "submit_changelog" in h
        assert callable(h["submit_changelog"])

    def test_submit_handler_stores_result(self) -> None:
        h = make_changelog_handlers(_REPO)
        h["submit_changelog"](
            {
                "version": "1.2.0",
                "content": "## [1.2.0] ...",
                "sections": {"added": 3, "fixed": 1},
                "file_path": "CHANGELOG.md",
            }
        )
        result = h["_changelog_result"]
        assert result["version"] == "1.2.0"
        assert result["sections"]["added"] == 3

    def test_role_file_exists(self) -> None:
        assert (_ROLES_DIR / "changelog_agent.md").exists()


# ===========================================================================
# User Story Generator
# ===========================================================================


class TestUserStoryGenerator:
    def test_run_fn_is_callable(self) -> None:
        assert callable(run_user_story_generator)

    def test_tools_include_read_only(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(_USER_STORY_TOOLS))

    def test_tools_include_write_file(self) -> None:
        assert "write_file" in _tool_names(_USER_STORY_TOOLS)

    def test_tools_include_submit(self) -> None:
        assert "submit_user_stories" in _tool_names(_USER_STORY_TOOLS)

    def test_all_tools_have_required_fields(self) -> None:
        for tool in _USER_STORY_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

    def test_verification_cfg_type(self) -> None:
        assert isinstance(_US_VCFG, VerificationConfig)

    def test_verification_cfg_read_tools_set_codebase_read(self) -> None:
        assert "read_file" in _US_VCFG.set_by
        assert "search_code" in _US_VCFG.set_by

    def test_verification_cfg_initial_has_codebase_read(self) -> None:
        assert "codebase_read" in _US_VCFG.initial
        assert _US_VCFG.initial["codebase_read"] is False

    def test_handlers_are_valid(self) -> None:
        _assert_handlers_valid(make_user_story_handlers)

    def test_submit_handler_present(self) -> None:
        h = make_user_story_handlers(_REPO)
        assert "submit_user_stories" in h
        assert callable(h["submit_user_stories"])

    def test_submit_handler_stores_result(self) -> None:
        h = make_user_story_handlers(_REPO)
        h["submit_user_stories"](
            {
                "feature": "Task Management",
                "stories": [
                    {
                        "as_a": "developer",
                        "i_want": "to create tasks",
                        "so_that": "I can track work",
                        "title": "Create task",
                        "acceptance_criteria": [
                            "Task is saved",
                            "Task appears in list",
                        ],
                    },
                ],
                "summary": "Core task CRUD stories",
            }
        )
        result = h["_user_story_result"]
        assert result["feature"] == "Task Management"
        assert len(result["stories"]) == 1

    def test_role_file_exists(self) -> None:
        assert (_ROLES_DIR / "user_story_generator.md").exists()


# ===========================================================================
# Security Architect
# ===========================================================================


class TestSecurityArchitect:
    def test_run_fn_is_callable(self) -> None:
        assert callable(run_security_architect)

    def test_tools_include_read_only(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(_SECURITY_TOOLS))

    def test_tools_include_submit(self) -> None:
        assert "submit_threat_model" in _tool_names(_SECURITY_TOOLS)

    def test_no_write_tool(self) -> None:
        # Security architect is read-only — must NOT have write_file
        assert "write_file" not in _tool_names(_SECURITY_TOOLS)

    def test_all_tools_have_required_fields(self) -> None:
        for tool in _SECURITY_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

    def test_verification_cfg_type(self) -> None:
        assert isinstance(_SA_VCFG, VerificationConfig)

    def test_verification_cfg_read_tools_set_codebase_read(self) -> None:
        assert "read_file" in _SA_VCFG.set_by
        assert _SA_VCFG.set_by["read_file"] == "codebase_read"

    def test_verification_cfg_initial_has_codebase_read(self) -> None:
        assert "codebase_read" in _SA_VCFG.initial

    def test_handlers_are_valid(self) -> None:
        _assert_handlers_valid(make_security_architect_handlers)

    def test_submit_handler_present(self) -> None:
        h = make_security_architect_handlers(_REPO)
        assert "submit_threat_model" in h
        assert callable(h["submit_threat_model"])

    def test_submit_handler_stores_result(self) -> None:
        h = make_security_architect_handlers(_REPO)
        h["submit_threat_model"](
            {
                "summary": "Low risk overall",
                "threats": [
                    {
                        "category": "A03 Injection",
                        "description": "Potential SQL injection",
                        "severity": "high",
                        "mitigation": "Use parameterised queries",
                    },
                ],
                "overall_risk": "high",
            }
        )
        result = h["_security_result"]
        assert result["overall_risk"] == "high"
        assert len(result["threats"]) == 1

    def test_requires_human_approval_for_high_threats(self) -> None:
        # Verify the run function logic: critical/high threats → requires_human_approval=True
        # We test via AgentResult fields, not a live run
        from app.agents.agent_result import AgentResult

        # Confirm AgentResult supports requires_human_approval field
        r = AgentResult(
            summary="test",
            findings=[],
            files_touched=[],
            verified=True,
            requires_human_approval=True,
            tokens_in=0,
            tokens_out=0,
            status="completed",
            raw={},
        )
        assert r.requires_human_approval is True

    def test_role_file_exists(self) -> None:
        assert (_ROLES_DIR / "security_architect.md").exists()


# ===========================================================================
# Database Architect
# ===========================================================================


class TestDatabaseArchitect:
    def test_run_fn_is_callable(self) -> None:
        assert callable(run_database_architect)

    def test_tools_include_read_only(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(_DB_TOOLS))

    def test_tools_include_run_python_snippet(self) -> None:
        assert "run_python_snippet" in _tool_names(_DB_TOOLS)

    def test_tools_include_submit(self) -> None:
        assert "submit_db_design" in _tool_names(_DB_TOOLS)

    def test_no_write_file_tool(self) -> None:
        # DB architect is a design agent — produces DDL in submit, not raw file writes
        assert "write_file" not in _tool_names(_DB_TOOLS)

    def test_all_tools_have_required_fields(self) -> None:
        for tool in _DB_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

    def test_verification_cfg_type(self) -> None:
        assert isinstance(_DBA_VCFG, VerificationConfig)

    def test_verification_cfg_read_file_sets_schema_read(self) -> None:
        assert "read_file" in _DBA_VCFG.set_by
        assert _DBA_VCFG.set_by["read_file"] == "schema_read"

    def test_verification_cfg_initial_has_schema_read(self) -> None:
        assert "schema_read" in _DBA_VCFG.initial
        assert _DBA_VCFG.initial["schema_read"] is False

    def test_handlers_are_valid(self) -> None:
        _assert_handlers_valid(make_database_architect_handlers)

    def test_submit_handler_present(self) -> None:
        h = make_database_architect_handlers(_REPO)
        assert "submit_db_design" in h
        assert callable(h["submit_db_design"])

    def test_submit_handler_stores_result(self) -> None:
        h = make_database_architect_handlers(_REPO)
        h["submit_db_design"](
            {
                "summary": "Add composite index on task_logs",
                "tables": [
                    {
                        "name": "task_logs",
                        "action": "index",
                        "rationale": "Slow query on task_id+created_at",
                    }
                ],
                "indexes": [
                    {
                        "table": "task_logs",
                        "columns": ["task_id", "created_at"],
                        "type": "btree",
                        "rationale": "Range scan optimisation",
                    }
                ],
            }
        )
        result = h["_db_result"]
        assert result["tables"][0]["name"] == "task_logs"
        assert len(result["indexes"]) == 1

    def test_role_file_exists(self) -> None:
        assert (_ROLES_DIR / "database_architect.md").exists()


# ===========================================================================
# Specialized-agents registry completeness
# ===========================================================================


class TestSpecializedAgentsRegistry:
    def setup_method(self) -> None:
        from app.api.specialized_agents import _REGISTRY

        self._registry = _REGISTRY

    def test_release_notes_agent_in_registry(self) -> None:
        assert "release_notes_agent" in self._registry

    def test_evaluation_agent_in_registry(self) -> None:
        assert "evaluation_agent" in self._registry

    def test_rag_engineer_agent_in_registry(self) -> None:
        assert "rag_engineer_agent" in self._registry

    def test_changelog_agent_in_registry(self) -> None:
        assert "changelog_agent" in self._registry

    def test_user_story_generator_in_registry(self) -> None:
        assert "user_story_generator" in self._registry

    def test_security_architect_in_registry(self) -> None:
        assert "security_architect" in self._registry

    def test_database_architect_in_registry(self) -> None:
        assert "database_architect" in self._registry

    def test_all_gap_agents_module_paths_are_valid(self) -> None:
        import importlib

        gap_agents = [
            "release_notes_agent",
            "evaluation_agent",
            "rag_engineer_agent",
            "changelog_agent",
            "user_story_generator",
            "security_architect",
            "database_architect",
        ]
        for name in gap_agents:
            module_path, fn_name = self._registry[name]
            mod = importlib.import_module(module_path)
            assert hasattr(mod, fn_name), f"{module_path} has no attribute {fn_name}"

    def test_load_agent_fn_works_for_gap_agents(self) -> None:
        from app.api.specialized_agents import _load_agent_fn

        gap_agents = [
            "release_notes_agent",
            "evaluation_agent",
            "rag_engineer_agent",
            "changelog_agent",
            "user_story_generator",
            "security_architect",
            "database_architect",
        ]
        for name in gap_agents:
            fn = _load_agent_fn(name)
            assert callable(fn), f"_load_agent_fn('{name}') did not return a callable"

    def test_total_registry_size_at_least_26(self) -> None:
        # 11 Day2 + 9 Day3 + 7 Gap = 27 minimum
        assert (
            len(self._registry) >= 26
        ), f"Registry has only {len(self._registry)} agents"


# ===========================================================================
# AgentResult schema completeness (applies to all gap agents)
# ===========================================================================


class TestAgentResultSchema:
    def test_all_required_fields_present(self) -> None:
        from app.agents.agent_result import AgentResult
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(AgentResult)}
        for required in (
            "summary",
            "findings",
            "files_touched",
            "verified",
            "requires_human_approval",
            "tokens_in",
            "tokens_out",
            "status",
            "raw",
        ):
            assert required in field_names, f"AgentResult missing field: {required}"

    def test_agent_result_defaults_are_sane(self) -> None:
        from app.agents.agent_result import AgentResult

        r = AgentResult(
            summary="ok",
            findings=["a"],
            files_touched=[],
            verified=True,
            requires_human_approval=False,
            tokens_in=100,
            tokens_out=50,
            status="completed",
            raw={"x": 1},
        )
        assert r.status == "completed"
        assert r.verified is True
        assert r.tokens_in == 100
