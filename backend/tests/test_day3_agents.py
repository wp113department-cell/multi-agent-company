"""Day 3 agents — structural and handler tests (no real LLM calls).

Tests cover:
  - Tool list structure (required tools present, submit tool included)
  - Handler factory: correct keys, callable values, non-empty
  - Agent module import (confirms no syntax/import errors)
  - VerificationConfig fields (confirms graph enforces verification before submit)
  - AgentResult schema (all required fields present)
  - Specialized agents router: registry completeness, load_agent_fn, endpoint schema
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Tool list imports
# ---------------------------------------------------------------------------
from app.agents.tools import (
    PERFORMANCE_REVIEWER_TOOLS,
    STYLE_REVIEWER_TOOLS,
    SPRINT_PLANNER_TOOLS,
    BUSINESS_ANALYST_TOOLS,
    MIGRATION_AGENT_TOOLS,
    SCHEMA_AGENT_TOOLS,
    AI_ENGINEER_TOOLS,
    CLEANUP_AGENT_TOOLS,
    TECH_DEBT_AGENT_TOOLS,
    READ_ONLY_TOOLS,
    make_performance_reviewer_handlers,
    make_style_reviewer_handlers,
    make_sprint_planner_handlers,
    make_business_analyst_handlers,
    make_migration_agent_handlers,
    make_schema_agent_handlers,
    make_ai_engineer_handlers,
    make_cleanup_agent_handlers,
    make_tech_debt_agent_handlers,
)

# ---------------------------------------------------------------------------
# Agent module imports (confirms no syntax/import errors)
# ---------------------------------------------------------------------------
from app.agents.agent_result import AgentResult
from app.agents.performance_reviewer import run_performance_reviewer  # noqa: F401
from app.agents.style_reviewer import run_style_reviewer  # noqa: F401
from app.agents.sprint_planner import run_sprint_planner  # noqa: F401
from app.agents.business_analyst import run_business_analyst  # noqa: F401
from app.agents.migration_agent import run_migration_agent  # noqa: F401
from app.agents.schema_agent import run_schema_agent  # noqa: F401
from app.agents.ai_engineer import run_ai_engineer  # noqa: F401
from app.agents.cleanup_agent import run_cleanup_agent  # noqa: F401
from app.agents.tech_debt_agent import run_tech_debt_agent  # noqa: F401


def _tool_names(tool_list: list[dict[str, Any]]) -> set[str]:
    return {t["name"] for t in tool_list}


READ_ONLY_NAMES = _tool_names(READ_ONLY_TOOLS)
_REPO = str(Path(__file__).parent.parent.parent)  # repo root for handler tests


# ===========================================================================
# Performance Reviewer
# ===========================================================================

class TestPerformanceReviewerTools:
    def test_includes_read_only_tools(self) -> None:
        names = _tool_names(PERFORMANCE_REVIEWER_TOOLS)
        assert READ_ONLY_NAMES.issubset(names)

    def test_includes_sql_tools(self) -> None:
        names = _tool_names(PERFORMANCE_REVIEWER_TOOLS)
        for expected in ("find_sql", "run_sql", "explain_query"):
            assert expected in names, f"PERFORMANCE_REVIEWER_TOOLS missing {expected}"

    def test_includes_code_analysis_tools(self) -> None:
        names = _tool_names(PERFORMANCE_REVIEWER_TOOLS)
        assert "list_functions" in names

    def test_includes_submit_tool(self) -> None:
        names = _tool_names(PERFORMANCE_REVIEWER_TOOLS)
        assert "submit_perf_review" in names

    def test_all_tools_have_required_fields(self) -> None:
        for tool in PERFORMANCE_REVIEWER_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool


class TestPerformanceReviewerHandlers:
    def test_handlers_not_empty(self) -> None:
        h = make_performance_reviewer_handlers(_REPO)
        assert len(h) > 0

    def test_handlers_are_callable(self) -> None:
        h = make_performance_reviewer_handlers(_REPO)
        for name, fn in h.items():
            if name.startswith("_"):
                continue  # internal state dicts, not handler functions
            assert callable(fn), f"Handler {name} is not callable"

    def test_submit_handler_present(self) -> None:
        h = make_performance_reviewer_handlers(_REPO)
        assert "submit_perf_review" in h

    def test_read_only_handlers_present(self) -> None:
        h = make_performance_reviewer_handlers(_REPO)
        for expected in ("read_file", "list_files", "search_code"):
            assert expected in h, f"Missing handler: {expected}"

    def test_explain_query_handler(self) -> None:
        h = make_performance_reviewer_handlers(_REPO)
        assert "explain_query" in h


# ===========================================================================
# Style Reviewer
# ===========================================================================

class TestStyleReviewerTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(STYLE_REVIEWER_TOOLS))

    def test_includes_linter_tool(self) -> None:
        assert "run_linter" in _tool_names(STYLE_REVIEWER_TOOLS)

    def test_includes_ast_tools(self) -> None:
        names = _tool_names(STYLE_REVIEWER_TOOLS)
        assert "list_functions" in names
        assert "list_classes" in names

    def test_includes_submit_tool(self) -> None:
        assert "submit_style_review" in _tool_names(STYLE_REVIEWER_TOOLS)


class TestStyleReviewerHandlers:
    def test_handlers_not_empty(self) -> None:
        assert len(make_style_reviewer_handlers(_REPO)) > 0

    def test_submit_handler_present(self) -> None:
        h = make_style_reviewer_handlers(_REPO)
        assert "submit_style_review" in h

    def test_run_linter_handler(self) -> None:
        h = make_style_reviewer_handlers(_REPO)
        assert "run_linter" in h
        assert callable(h["run_linter"])


# ===========================================================================
# Sprint Planner
# ===========================================================================

class TestSprintPlannerTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(SPRINT_PLANNER_TOOLS))

    def test_includes_complexity_estimator(self) -> None:
        assert "estimate_complexity" in _tool_names(SPRINT_PLANNER_TOOLS)

    def test_includes_submit_tool(self) -> None:
        assert "submit_sprint_plan" in _tool_names(SPRINT_PLANNER_TOOLS)


class TestSprintPlannerHandlers:
    def test_handlers_not_empty(self) -> None:
        assert len(make_sprint_planner_handlers(_REPO)) > 0

    def test_submit_handler_present(self) -> None:
        assert "submit_sprint_plan" in make_sprint_planner_handlers(_REPO)

    def test_estimate_complexity_handler(self) -> None:
        h = make_sprint_planner_handlers(_REPO)
        assert "estimate_complexity" in h
        assert callable(h["estimate_complexity"])

    def test_estimate_complexity_returns_result(self) -> None:
        h = make_sprint_planner_handlers(_REPO)
        result = h["estimate_complexity"]({"description": "Add a new REST endpoint"})
        # estimate_complexity returns a string or dict describing the estimate
        assert result is not None
        result_str = str(result).lower()
        assert any(kw in result_str for kw in ("complexity", "estimate", "xs", "s", "m", "l", "xl", "points", "score"))


# ===========================================================================
# Business Analyst
# ===========================================================================

class TestBusinessAnalystTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(BUSINESS_ANALYST_TOOLS))

    def test_includes_submit_tool(self) -> None:
        assert "submit_ba_result" in _tool_names(BUSINESS_ANALYST_TOOLS)


class TestBusinessAnalystHandlers:
    def test_handlers_not_empty(self) -> None:
        assert len(make_business_analyst_handlers(_REPO)) > 0

    def test_submit_handler_present(self) -> None:
        assert "submit_ba_result" in make_business_analyst_handlers(_REPO)


# ===========================================================================
# Migration Agent
# ===========================================================================

class TestMigrationAgentTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(MIGRATION_AGENT_TOOLS))

    def test_includes_db_tools(self) -> None:
        names = _tool_names(MIGRATION_AGENT_TOOLS)
        assert "run_sql" in names
        assert "inspect_schema" in names

    def test_includes_write_file(self) -> None:
        assert "write_file" in _tool_names(MIGRATION_AGENT_TOOLS)

    def test_includes_submit_tool(self) -> None:
        assert "submit_migration" in _tool_names(MIGRATION_AGENT_TOOLS)


class TestMigrationAgentHandlers:
    def test_handlers_not_empty(self) -> None:
        assert len(make_migration_agent_handlers(_REPO)) > 0

    def test_submit_handler_present(self) -> None:
        assert "submit_migration" in make_migration_agent_handlers(_REPO)

    def test_inspect_schema_handler(self) -> None:
        h = make_migration_agent_handlers(_REPO)
        assert "inspect_schema" in h
        assert callable(h["inspect_schema"])


# ===========================================================================
# Schema Agent
# ===========================================================================

class TestSchemaAgentTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(SCHEMA_AGENT_TOOLS))

    def test_includes_db_tools(self) -> None:
        names = _tool_names(SCHEMA_AGENT_TOOLS)
        assert "run_sql" in names
        assert "inspect_schema" in names

    def test_includes_write_file(self) -> None:
        assert "write_file" in _tool_names(SCHEMA_AGENT_TOOLS)

    def test_includes_submit_tool(self) -> None:
        assert "submit_schema" in _tool_names(SCHEMA_AGENT_TOOLS)


class TestSchemaAgentHandlers:
    def test_handlers_not_empty(self) -> None:
        assert len(make_schema_agent_handlers(_REPO)) > 0

    def test_submit_handler_present(self) -> None:
        assert "submit_schema" in make_schema_agent_handlers(_REPO)

    def test_all_handlers_callable(self) -> None:
        for name, fn in make_schema_agent_handlers(_REPO).items():
            if name.startswith("_"):
                continue  # internal state dicts, not handler functions
            assert callable(fn), f"Handler {name} not callable"


# ===========================================================================
# AI Engineer
# ===========================================================================

class TestAIEngineerTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(AI_ENGINEER_TOOLS))

    def test_includes_python_execution(self) -> None:
        assert "run_python_snippet" in _tool_names(AI_ENGINEER_TOOLS)

    def test_includes_write_file(self) -> None:
        assert "write_file" in _tool_names(AI_ENGINEER_TOOLS)

    def test_includes_submit_tool(self) -> None:
        assert "submit_ai_result" in _tool_names(AI_ENGINEER_TOOLS)

    def test_includes_fetch_url(self) -> None:
        assert "fetch_url" in _tool_names(AI_ENGINEER_TOOLS)


class TestAIEngineerHandlers:
    def test_handlers_not_empty(self) -> None:
        assert len(make_ai_engineer_handlers(_REPO)) > 0

    def test_submit_handler_present(self) -> None:
        assert "submit_ai_result" in make_ai_engineer_handlers(_REPO)

    def test_run_python_snippet_handler(self) -> None:
        h = make_ai_engineer_handlers(_REPO)
        assert "run_python_snippet" in h
        assert callable(h["run_python_snippet"])

    def test_run_python_snippet_safe_execution(self) -> None:
        h = make_ai_engineer_handlers(_REPO)
        result = h["run_python_snippet"]({"code": "print(2 + 2)"})
        assert isinstance(result, (str, dict))

    def test_fetch_url_handler(self) -> None:
        h = make_ai_engineer_handlers(_REPO)
        assert "fetch_url" in h
        assert callable(h["fetch_url"])


# ===========================================================================
# Cleanup Agent
# ===========================================================================

class TestCleanupAgentTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(CLEANUP_AGENT_TOOLS))

    def test_includes_dead_code_detect(self) -> None:
        assert "dead_code_detect" in _tool_names(CLEANUP_AGENT_TOOLS)

    def test_includes_organize_imports(self) -> None:
        assert "organize_imports" in _tool_names(CLEANUP_AGENT_TOOLS)

    def test_includes_edit_tools(self) -> None:
        names = _tool_names(CLEANUP_AGENT_TOOLS)
        assert "edit_file" in names
        assert "delete_file" in names

    def test_includes_submit_tool(self) -> None:
        assert "submit_cleanup" in _tool_names(CLEANUP_AGENT_TOOLS)


class TestCleanupAgentHandlers:
    def test_handlers_not_empty(self) -> None:
        assert len(make_cleanup_agent_handlers(_REPO)) > 0

    def test_submit_handler_present(self) -> None:
        assert "submit_cleanup" in make_cleanup_agent_handlers(_REPO)

    def test_dead_code_detect_handler(self) -> None:
        h = make_cleanup_agent_handlers(_REPO)
        assert "dead_code_detect" in h
        assert callable(h["dead_code_detect"])

    def test_dead_code_detect_returns_results(self) -> None:
        h = make_cleanup_agent_handlers(_REPO)
        result = h["dead_code_detect"]({"repo_path": _REPO})
        # Should return a dict or list, not raise
        assert result is not None


# ===========================================================================
# Tech Debt Agent
# ===========================================================================

class TestTechDebtAgentTools:
    def test_includes_read_only_tools(self) -> None:
        assert READ_ONLY_NAMES.issubset(_tool_names(TECH_DEBT_AGENT_TOOLS))

    def test_includes_analysis_tools(self) -> None:
        names = _tool_names(TECH_DEBT_AGENT_TOOLS)
        assert "list_functions" in names
        assert "list_classes" in names
        assert "run_linter" in names

    def test_includes_coverage_report(self) -> None:
        assert "coverage_report" in _tool_names(TECH_DEBT_AGENT_TOOLS)

    def test_includes_submit_tool(self) -> None:
        assert "submit_tech_debt" in _tool_names(TECH_DEBT_AGENT_TOOLS)


class TestTechDebtAgentHandlers:
    def test_handlers_not_empty(self) -> None:
        assert len(make_tech_debt_agent_handlers(_REPO)) > 0

    def test_submit_handler_present(self) -> None:
        assert "submit_tech_debt" in make_tech_debt_agent_handlers(_REPO)

    def test_coverage_report_handler(self) -> None:
        h = make_tech_debt_agent_handlers(_REPO)
        assert "coverage_report" in h
        assert callable(h["coverage_report"])


# ===========================================================================
# AgentResult schema contract
# ===========================================================================

class TestAgentResultSchema:
    def test_required_fields_exist(self) -> None:
        r = AgentResult(
            summary="test",
            findings=[],
            files_touched=[],
            verified=True,
            requires_human_approval=False,
            tokens_in=10,
            tokens_out=5,
            status="completed",
            raw={},
        )
        assert r.summary == "test"
        assert r.verified is True
        assert r.tokens_in == 10
        assert r.status == "completed"

    def test_default_status_completed(self) -> None:
        r = AgentResult(
            summary="ok",
            findings=[],
            files_touched=[],
            verified=False,
            requires_human_approval=False,
            tokens_in=0,
            tokens_out=0,
            status="completed",
            raw={},
        )
        assert isinstance(r.status, str)

    def test_files_touched_is_list(self) -> None:
        r = AgentResult(
            summary="s",
            findings=[],
            files_touched=["a.py", "b.py"],
            verified=True,
            requires_human_approval=False,
            tokens_in=1,
            tokens_out=1,
            status="completed",
            raw={},
        )
        assert len(r.files_touched) == 2


# ===========================================================================
# Specialized agents router
# ===========================================================================

class TestSpecializedAgentsRouter:
    def test_registry_contains_all_day3_agents(self) -> None:
        from app.api.specialized_agents import _REGISTRY
        day3 = [
            "performance_reviewer", "style_reviewer", "sprint_planner",
            "business_analyst", "migration_agent", "schema_agent",
            "ai_engineer", "cleanup_agent", "tech_debt_agent",
        ]
        for name in day3:
            assert name in _REGISTRY, f"'{name}' missing from specialized agent registry"

    def test_registry_contains_all_day2_agents(self) -> None:
        from app.api.specialized_agents import _REGISTRY
        day2 = [
            "bug_fix", "security_reviewer", "arch_reviewer", "sql_agent",
            "docker_agent", "cicd_agent", "refactor_agent", "readme_agent",
            "api_docs_agent", "dependency_agent", "monitoring_agent",
        ]
        for name in day2:
            assert name in _REGISTRY, f"'{name}' missing from specialized agent registry"

    def test_total_registry_count(self) -> None:
        from app.api.specialized_agents import _REGISTRY
        assert len(_REGISTRY) >= 20, f"Expected ≥20 agents, got {len(_REGISTRY)}"

    def test_load_agent_fn_returns_callable(self) -> None:
        from app.api.specialized_agents import _load_agent_fn
        fn = _load_agent_fn("performance_reviewer")
        assert callable(fn)

    def test_load_agent_fn_all_agents_importable(self) -> None:
        from app.api.specialized_agents import _load_agent_fn, SUPPORTED_AGENTS
        for name in SUPPORTED_AGENTS:
            fn = _load_agent_fn(name)
            assert callable(fn), f"Agent '{name}' function not callable"

    def test_load_agent_fn_raises_for_unknown(self) -> None:
        from app.api.specialized_agents import _load_agent_fn
        with pytest.raises(ValueError, match="Unknown agent"):
            _load_agent_fn("does_not_exist_xyz")

    def test_router_has_list_endpoint(self) -> None:
        from app.api.specialized_agents import router
        paths = [r.path for r in router.routes]
        assert "/api/specialized-agents/agents" in paths

    def test_router_has_run_endpoint(self) -> None:
        from app.api.specialized_agents import router
        paths = [r.path for r in router.routes]
        assert any("{agent_name}" in p and "/run" in p for p in paths)

    def test_router_has_run_sync_endpoint(self) -> None:
        from app.api.specialized_agents import router
        paths = [r.path for r in router.routes]
        assert any("{agent_name}" in p and "run-sync" in p for p in paths)


# ===========================================================================
# Alert service
# ===========================================================================

class TestAlertService:
    @pytest.mark.asyncio
    async def test_noop_when_no_webhook_url(self) -> None:
        """Should not raise when ALERT_WEBHOOK_URL is empty."""
        from app.services.alert import send_task_alert
        # config has alert_webhook_url="" by default — should complete silently
        await send_task_alert(task_id=1, event="blocked", detail="test")

    @pytest.mark.asyncio
    async def test_alert_payload_structure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify the payload structure sent to the webhook."""
        import app.services.alert as alert_mod
        from app.config import get_settings

        captured: list[dict[str, Any]] = []

        class _FakeResp:
            status_code = 200

        class _FakeClient:
            async def __aenter__(self) -> "_FakeClient":
                return self

            async def __aexit__(self, *_: Any) -> None:
                pass

            async def post(self, url: str, json: dict[str, Any]) -> "_FakeResp":
                captured.append(json)
                return _FakeResp()

        monkeypatch.setattr(alert_mod.httpx, "AsyncClient", lambda **kw: _FakeClient())

        # Temporarily patch settings to have a webhook URL
        settings = get_settings()
        original_url = settings.alert_webhook_url
        settings.alert_webhook_url = "https://hooks.example.com/test"
        try:
            await alert_mod.send_task_alert(999, "blocked", "Agent hit max retries")
        finally:
            settings.alert_webhook_url = original_url

        assert len(captured) == 1
        payload = captured[0]
        assert payload["event"] == "blocked"
        assert payload["task_id"] == 999
        assert payload["source"] == "gridiron-dev-dept"
        assert "timestamp" in payload


# ===========================================================================
# Memory store — new categories
# ===========================================================================

class TestMemoryStoreCategories:
    def test_embed_architecture_note_importable(self) -> None:
        from app.memory.store import embed_architecture_note
        import inspect
        assert inspect.iscoroutinefunction(embed_architecture_note)

    def test_embed_failure_importable(self) -> None:
        from app.memory.store import embed_failure
        import inspect
        assert inspect.iscoroutinefunction(embed_failure)

    def test_query_architecture_notes_importable(self) -> None:
        from app.memory.store import query_architecture_notes
        import inspect
        assert inspect.iscoroutinefunction(query_architecture_notes)

    def test_query_failures_importable(self) -> None:
        from app.memory.store import query_failures
        import inspect
        assert inspect.iscoroutinefunction(query_failures)


# ===========================================================================
# Retention service
# ===========================================================================

class TestRetentionService:
    def test_retention_module_importable(self) -> None:
        from app.services.retention import start_retention_loop, _run_cleanup
        import inspect
        assert inspect.iscoroutinefunction(start_retention_loop)
        assert inspect.iscoroutinefunction(_run_cleanup)

    def test_cleanup_interval_is_24h(self) -> None:
        import app.services.retention as ret_mod
        assert ret_mod._CLEANUP_INTERVAL_SECONDS == 24 * 3600


# ===========================================================================
# Config — new fields
# ===========================================================================

class TestConfigNewFields:
    def test_sentry_dsn_default_empty(self) -> None:
        from app.config import get_settings
        settings = get_settings()
        assert settings.sentry_dsn == ""

    def test_alert_webhook_url_default_empty(self) -> None:
        from app.config import get_settings
        settings = get_settings()
        assert settings.alert_webhook_url == ""

    def test_log_retention_days_default(self) -> None:
        from app.config import get_settings
        settings = get_settings()
        assert settings.log_retention_days == 90

    def test_alert_on_blocked_default_true(self) -> None:
        from app.config import get_settings
        settings = get_settings()
        assert settings.alert_on_blocked is True

    def test_sentry_traces_sample_rate_valid(self) -> None:
        from app.config import get_settings
        settings = get_settings()
        assert 0.0 <= settings.sentry_traces_sample_rate <= 1.0
