"""Day 4 agents — structural and handler tests (no real LLM calls).

Tests cover:
  - Tool list structure (submit tool present, all tools have required fields)
  - Handler factory: correct keys, callable values, non-empty
  - Submit handler invocation: returns string, updates internal state dict
  - Module import sanity (no syntax/import errors)
  - VerificationConfig enforce_in_result: correct set_by key
  - Specialized agents router: Day 4 entries registered

Day 4 agents (8):
  release_notes_agent, evaluation_agent, rag_engineer_agent, changelog_agent,
  user_story_generator, security_architect, database_architect, manager
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Handler factory imports (inline in each agent module, not in tools.py)
# ---------------------------------------------------------------------------
from app.agents.release_notes_agent import (
    make_release_notes_handlers,
    _RELEASE_NOTES_TOOLS,
    _VERIFICATION_CFG as _RN_VCFG,
)
from app.agents.evaluation_agent import (
    make_evaluation_handlers,
    _EVAL_TOOLS,
    _VERIFICATION_CFG as _EVAL_VCFG,
)
from app.agents.rag_engineer_agent import (
    make_rag_engineer_handlers,
    _RAG_TOOLS,
    _VERIFICATION_CFG as _RAG_VCFG,
)
from app.agents.changelog_agent import (
    make_changelog_handlers,
    _CHANGELOG_TOOLS,
    _VERIFICATION_CFG as _CL_VCFG,
)
from app.agents.user_story_generator import (
    make_user_story_handlers,
    _USER_STORY_TOOLS,
    _VERIFICATION_CFG as _US_VCFG,
)
from app.agents.security_architect import (
    make_security_architect_handlers,
    _SECURITY_TOOLS,
    _VERIFICATION_CFG as _SA_VCFG,
)
from app.agents.database_architect import (
    make_database_architect_handlers,
    _DB_TOOLS,
    _VERIFICATION_CFG as _DA_VCFG,
)
from app.agents.manager import run_manager  # noqa: F401 (import sanity check)
from app.agents.tools import READ_ONLY_TOOLS

_REPO = str(Path(__file__).parent.parent.parent)


def _tool_names(tool_list: list[dict[str, Any]]) -> set[str]:
    return {t["name"] for t in tool_list}


READ_ONLY_NAMES = _tool_names(READ_ONLY_TOOLS)


# ===========================================================================
# Release Notes Agent
# ===========================================================================

class TestReleaseNotesTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(_RELEASE_NOTES_TOOLS))

    def test_includes_submit_tool(self) -> None:
        assert "submit_release_notes" in _tool_names(_RELEASE_NOTES_TOOLS)

    def test_includes_git_tools(self) -> None:
        names = _tool_names(_RELEASE_NOTES_TOOLS)
        assert "git_log" in names

    def test_includes_generate_tools(self) -> None:
        names = _tool_names(_RELEASE_NOTES_TOOLS)
        assert "generate_release_notes" in names or "generate_changelog" in names

    def test_all_tools_have_required_fields(self) -> None:
        for tool in _RELEASE_NOTES_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool


class TestReleaseNotesHandlers:
    def test_handlers_not_empty(self) -> None:
        h = make_release_notes_handlers(_REPO)
        assert len(h) > 0

    def test_submit_handler_present(self) -> None:
        assert "submit_release_notes" in make_release_notes_handlers(_REPO)

    def test_read_only_handlers_present(self) -> None:
        h = make_release_notes_handlers(_REPO)
        for name in ("read_file", "list_files", "search_code"):
            assert name in h, f"Missing handler: {name}"

    def test_all_non_internal_handlers_callable(self) -> None:
        for name, fn in make_release_notes_handlers(_REPO).items():
            if name.startswith("_"):
                continue
            assert callable(fn), f"Handler {name!r} is not callable"

    def test_submit_handler_returns_string(self) -> None:
        h = make_release_notes_handlers(_REPO)
        result = h["submit_release_notes"]({
            "version": "v1.2.0",
            "content": "# Release notes",
            "highlights": ["Feature A"],
            "breaking_changes": [],
        })
        assert isinstance(result, str)
        assert "v1.2.0" in result

    def test_submit_handler_updates_result_dict(self) -> None:
        h = make_release_notes_handlers(_REPO)
        h["submit_release_notes"]({"version": "v2.0.0", "content": "# v2", "highlights": []})
        assert h["_release_notes_result"]["version"] == "v2.0.0"


class TestReleaseNotesVerification:
    def test_enforce_in_result_non_empty(self) -> None:
        assert len(_RN_VCFG.enforce_in_result) > 0

    def test_set_by_has_tool_key(self) -> None:
        assert len(_RN_VCFG.set_by) > 0


# ===========================================================================
# Evaluation Agent
# ===========================================================================

class TestEvaluationTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(_EVAL_TOOLS))

    def test_includes_submit_tool(self) -> None:
        assert "submit_eval_result" in _tool_names(_EVAL_TOOLS)

    def test_includes_python_execution(self) -> None:
        assert "run_python_snippet" in _tool_names(_EVAL_TOOLS)

    def test_all_tools_have_required_fields(self) -> None:
        for tool in _EVAL_TOOLS:
            assert "name" in tool and "description" in tool and "input_schema" in tool


class TestEvaluationHandlers:
    def test_handlers_not_empty(self) -> None:
        assert len(make_evaluation_handlers(_REPO)) > 0

    def test_submit_handler_present(self) -> None:
        assert "submit_eval_result" in make_evaluation_handlers(_REPO)

    def test_all_non_internal_handlers_callable(self) -> None:
        for name, fn in make_evaluation_handlers(_REPO).items():
            if name.startswith("_"):
                continue
            assert callable(fn)

    def test_submit_handler_returns_string(self) -> None:
        h = make_evaluation_handlers(_REPO)
        result = h["submit_eval_result"]({
            "overall_score": 0.85,
            "pass_count": 17,
            "fail_count": 3,
            "cases": [],
            "summary": "Good quality",
        })
        assert isinstance(result, str)

    def test_submit_handler_updates_result_dict(self) -> None:
        h = make_evaluation_handlers(_REPO)
        h["submit_eval_result"]({"overall_score": 0.7, "pass_count": 7, "fail_count": 3, "cases": []})
        assert h["_eval_result"]["overall_score"] == 0.7


class TestEvaluationVerification:
    def test_enforce_in_result_non_empty(self) -> None:
        assert len(_EVAL_VCFG.enforce_in_result) > 0

    def test_set_by_includes_run_python_snippet(self) -> None:
        assert "run_python_snippet" in _EVAL_VCFG.set_by


# ===========================================================================
# RAG Engineer Agent
# ===========================================================================

class TestRagEngineerTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(_RAG_TOOLS))

    def test_includes_submit_tool(self) -> None:
        assert "submit_rag_design" in _tool_names(_RAG_TOOLS)

    def test_includes_write_file(self) -> None:
        assert "write_file" in _tool_names(_RAG_TOOLS)

    def test_includes_python_execution(self) -> None:
        assert "run_python_snippet" in _tool_names(_RAG_TOOLS)

    def test_all_tools_have_required_fields(self) -> None:
        for tool in _RAG_TOOLS:
            assert "name" in tool and "description" in tool and "input_schema" in tool


class TestRagEngineerHandlers:
    def test_handlers_not_empty(self) -> None:
        assert len(make_rag_engineer_handlers(_REPO)) > 0

    def test_submit_handler_present(self) -> None:
        assert "submit_rag_design" in make_rag_engineer_handlers(_REPO)

    def test_all_non_internal_handlers_callable(self) -> None:
        for name, fn in make_rag_engineer_handlers(_REPO).items():
            if name.startswith("_"):
                continue
            assert callable(fn)

    def test_submit_handler_returns_string(self) -> None:
        h = make_rag_engineer_handlers(_REPO)
        result = h["submit_rag_design"]({
            "summary": "Hybrid RAG using pgvector",
            "vector_store": "pgvector",
            "embedding_model": "voyage-code-2",
            "chunking_strategy": "recursive-character",
            "retrieval_strategy": "top-k",
            "implementation_notes": [],
            "files_written": [],
        })
        assert isinstance(result, str)

    def test_submit_handler_updates_result_dict(self) -> None:
        h = make_rag_engineer_handlers(_REPO)
        h["submit_rag_design"]({"vector_store": "Qdrant", "embedding_model": "text-embedding-3-small"})
        assert h["_rag_result"]["vector_store"] == "Qdrant"


class TestRagEngineerVerification:
    def test_enforce_in_result_non_empty(self) -> None:
        assert len(_RAG_VCFG.enforce_in_result) > 0

    def test_set_by_has_read_file_key(self) -> None:
        assert "read_file" in _RAG_VCFG.set_by


# ===========================================================================
# Changelog Agent
# ===========================================================================

class TestChangelogTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(_CHANGELOG_TOOLS))

    def test_includes_submit_tool(self) -> None:
        assert "submit_changelog" in _tool_names(_CHANGELOG_TOOLS)

    def test_includes_git_tools(self) -> None:
        names = _tool_names(_CHANGELOG_TOOLS)
        assert "git_log" in names

    def test_includes_generate_changelog(self) -> None:
        assert "generate_changelog" in _tool_names(_CHANGELOG_TOOLS)

    def test_includes_write_file(self) -> None:
        assert "write_file" in _tool_names(_CHANGELOG_TOOLS)

    def test_all_tools_have_required_fields(self) -> None:
        for tool in _CHANGELOG_TOOLS:
            assert "name" in tool and "description" in tool and "input_schema" in tool


class TestChangelogHandlers:
    def test_handlers_not_empty(self) -> None:
        assert len(make_changelog_handlers(_REPO)) > 0

    def test_submit_handler_present(self) -> None:
        assert "submit_changelog" in make_changelog_handlers(_REPO)

    def test_all_non_internal_handlers_callable(self) -> None:
        for name, fn in make_changelog_handlers(_REPO).items():
            if name.startswith("_"):
                continue
            assert callable(fn)

    def test_submit_handler_returns_string(self) -> None:
        h = make_changelog_handlers(_REPO)
        result = h["submit_changelog"]({
            "version": "1.3.0",
            "content": "## [1.3.0]",
            "sections": {"added": 2, "fixed": 1},
            "file_path": "CHANGELOG.md",
        })
        assert isinstance(result, str)
        assert "1.3.0" in result

    def test_submit_handler_updates_result_dict(self) -> None:
        h = make_changelog_handlers(_REPO)
        h["submit_changelog"]({"version": "2.0.0", "content": "## [2.0.0]", "sections": {}})
        assert h["_changelog_result"]["version"] == "2.0.0"


class TestChangelogVerification:
    def test_enforce_in_result_non_empty(self) -> None:
        assert len(_CL_VCFG.enforce_in_result) > 0

    def test_set_by_includes_generate_changelog(self) -> None:
        assert "generate_changelog" in _CL_VCFG.set_by


# ===========================================================================
# User Story Generator
# ===========================================================================

class TestUserStoryTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(_USER_STORY_TOOLS))

    def test_includes_submit_tool(self) -> None:
        assert "submit_user_stories" in _tool_names(_USER_STORY_TOOLS)

    def test_includes_write_file(self) -> None:
        assert "write_file" in _tool_names(_USER_STORY_TOOLS)

    def test_all_tools_have_required_fields(self) -> None:
        for tool in _USER_STORY_TOOLS:
            assert "name" in tool and "description" in tool and "input_schema" in tool


class TestUserStoryHandlers:
    def test_handlers_not_empty(self) -> None:
        assert len(make_user_story_handlers(_REPO)) > 0

    def test_submit_handler_present(self) -> None:
        assert "submit_user_stories" in make_user_story_handlers(_REPO)

    def test_all_non_internal_handlers_callable(self) -> None:
        for name, fn in make_user_story_handlers(_REPO).items():
            if name.startswith("_"):
                continue
            assert callable(fn)

    def test_submit_handler_returns_string(self) -> None:
        h = make_user_story_handlers(_REPO)
        result = h["submit_user_stories"]({
            "feature": "login",
            "stories": [
                {
                    "title": "User Login",
                    "as_a": "registered user",
                    "i_want": "to log in",
                    "so_that": "I can access my dashboard",
                    "acceptance_criteria": ["Redirects to dashboard"],
                }
            ],
            "summary": "1 story generated",
        })
        assert isinstance(result, str)
        assert "login" in result.lower() or "1" in result

    def test_submit_handler_updates_result_dict(self) -> None:
        h = make_user_story_handlers(_REPO)
        h["submit_user_stories"]({"feature": "signup", "stories": [], "summary": "done"})
        assert h["_user_story_result"]["feature"] == "signup"


class TestUserStoryVerification:
    def test_enforce_in_result_non_empty(self) -> None:
        assert len(_US_VCFG.enforce_in_result) > 0

    def test_set_by_has_read_file_key(self) -> None:
        assert "read_file" in _US_VCFG.set_by


# ===========================================================================
# Security Architect
# ===========================================================================

class TestSecurityArchitectTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(_SECURITY_TOOLS))

    def test_includes_submit_tool(self) -> None:
        assert "submit_threat_model" in _tool_names(_SECURITY_TOOLS)

    def test_no_write_file_tool(self) -> None:
        assert "write_file" not in _tool_names(_SECURITY_TOOLS)

    def test_all_tools_have_required_fields(self) -> None:
        for tool in _SECURITY_TOOLS:
            assert "name" in tool and "description" in tool and "input_schema" in tool


class TestSecurityArchitectHandlers:
    def test_handlers_not_empty(self) -> None:
        assert len(make_security_architect_handlers(_REPO)) > 0

    def test_submit_handler_present(self) -> None:
        assert "submit_threat_model" in make_security_architect_handlers(_REPO)

    def test_all_non_internal_handlers_callable(self) -> None:
        for name, fn in make_security_architect_handlers(_REPO).items():
            if name.startswith("_"):
                continue
            assert callable(fn)

    def test_submit_handler_returns_string(self) -> None:
        h = make_security_architect_handlers(_REPO)
        result = h["submit_threat_model"]({
            "summary": "Moderate risk overall",
            "threats": [
                {
                    "category": "Elevation of Privilege",
                    "description": "Missing RBAC on /admin route",
                    "severity": "high",
                    "mitigation": "Add @require_role('admin') decorator",
                }
            ],
            "owasp_findings": ["A01:2021"],
            "recommendations": ["Add rate limiting"],
            "overall_risk": "medium",
        })
        assert isinstance(result, str)
        assert "medium" in result.lower() or "1" in result

    def test_submit_handler_updates_result_dict(self) -> None:
        h = make_security_architect_handlers(_REPO)
        h["submit_threat_model"]({"summary": "OK", "threats": [], "overall_risk": "low"})
        assert h["_security_result"]["overall_risk"] == "low"


class TestSecurityArchitectVerification:
    def test_enforce_in_result_non_empty(self) -> None:
        assert len(_SA_VCFG.enforce_in_result) > 0

    def test_set_by_has_read_file_key(self) -> None:
        assert "read_file" in _SA_VCFG.set_by


# ===========================================================================
# Database Architect
# ===========================================================================

class TestDatabaseArchitectTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(_DB_TOOLS))

    def test_includes_submit_tool(self) -> None:
        assert "submit_db_design" in _tool_names(_DB_TOOLS)

    def test_includes_python_execution(self) -> None:
        assert "run_python_snippet" in _tool_names(_DB_TOOLS)

    def test_all_tools_have_required_fields(self) -> None:
        for tool in _DB_TOOLS:
            assert "name" in tool and "description" in tool and "input_schema" in tool


class TestDatabaseArchitectHandlers:
    def test_handlers_not_empty(self) -> None:
        assert len(make_database_architect_handlers(_REPO)) > 0

    def test_submit_handler_present(self) -> None:
        assert "submit_db_design" in make_database_architect_handlers(_REPO)

    def test_all_non_internal_handlers_callable(self) -> None:
        for name, fn in make_database_architect_handlers(_REPO).items():
            if name.startswith("_"):
                continue
            assert callable(fn)

    def test_submit_handler_returns_string(self) -> None:
        h = make_database_architect_handlers(_REPO)
        result = h["submit_db_design"]({
            "summary": "Add indexes to tasks table",
            "tables": [
                {"name": "tasks", "action": "index", "rationale": "Speeds up status filter queries"},
            ],
            "indexes": [
                {"table": "tasks", "columns": ["status", "created_at"], "type": "btree", "rationale": "Compound index for common filter"},
            ],
            "migration_notes": ["Non-blocking CONCURRENTLY index"],
        })
        assert isinstance(result, str)
        assert "1" in result

    def test_submit_handler_updates_result_dict(self) -> None:
        h = make_database_architect_handlers(_REPO)
        h["submit_db_design"]({"summary": "Schema OK", "tables": []})
        assert h["_db_result"]["summary"] == "Schema OK"


class TestDatabaseArchitectVerification:
    def test_enforce_in_result_non_empty(self) -> None:
        assert len(_DA_VCFG.enforce_in_result) > 0

    def test_set_by_has_read_file_key(self) -> None:
        assert "read_file" in _DA_VCFG.set_by


# ===========================================================================
# Manager (orchestrator — no tool list or submit handler)
# ===========================================================================

class TestManagerModule:
    def test_imports_cleanly(self) -> None:
        import app.agents.manager as mgr  # noqa: F401
        assert hasattr(mgr, "run_manager")

    def test_agent_contract_present(self) -> None:
        from app.agents.manager import AGENT_CONTRACT
        assert AGENT_CONTRACT["name"] == "manager"
        assert AGENT_CONTRACT["risk_level"] in ("low", "medium", "high")

    def test_manager_has_no_llm_tools(self) -> None:
        from app.agents.manager import AGENT_CONTRACT
        assert AGENT_CONTRACT["allowed_tools"] == []

    def test_manager_dependencies_non_empty(self) -> None:
        from app.agents.manager import AGENT_CONTRACT
        assert len(AGENT_CONTRACT["dependencies"]) > 0


# ===========================================================================
# Specialized agents router: Day 4 entries
# ===========================================================================

class TestSpecializedAgentsDay4:
    def test_registry_contains_day4_agents(self) -> None:
        from app.api.specialized_agents import _REGISTRY
        day4 = [
            "release_notes_agent", "evaluation_agent", "rag_engineer_agent",
            "changelog_agent", "user_story_generator", "security_architect",
            "database_architect",
        ]
        for name in day4:
            assert name in _REGISTRY, f"'{name}' missing from specialized agent registry"

    def test_total_registry_count_includes_day4(self) -> None:
        from app.api.specialized_agents import _REGISTRY
        assert len(_REGISTRY) >= 27, f"Expected ≥27 agents (Days 0-4), got {len(_REGISTRY)}"

    def test_day4_agent_fns_callable(self) -> None:
        from app.api.specialized_agents import _load_agent_fn
        day4 = [
            "release_notes_agent", "evaluation_agent", "rag_engineer_agent",
            "changelog_agent", "user_story_generator", "security_architect",
            "database_architect",
        ]
        for name in day4:
            fn = _load_agent_fn(name)
            assert callable(fn), f"Agent fn for '{name}' is not callable"
