"""Full LangGraph pipeline E2E tests — require ANTHROPIC_API_KEY."""
from __future__ import annotations

import asyncio
import pytest
from tests.pending.conftest import requires_anthropic

_THIS_REPO = "/home/pc-117/Documents/CRR2906"


@requires_anthropic
class TestPipelineE2E:
    """End-to-end: PM → Architect → Decomposer via LangGraph StateGraph."""

    def test_full_pipeline_completes(self) -> None:
        """Pipeline runs PM → Architect → Decomposer without blocking."""
        from app.pipeline.graph import run_planning_pipeline

        result = asyncio.run(
            run_planning_pipeline(
                task_id=50,
                title="Add GET /health endpoint",
                description=(
                    "Add a GET /health route to FastAPI app returning "
                    '{"status": "ok"} with HTTP 200.'
                ),
                repo_path=_THIS_REPO,
            )
        )

        assert result.get("stage") != "blocked", f"Pipeline blocked: {result.get('error')}"
        assert "pm_brief" in result, "Pipeline missing pm_brief"
        assert "architect_plan" in result, "Pipeline missing architect_plan"
        assert "subtasks" in result, "Pipeline missing subtasks"
        assert len(result["subtasks"]) >= 1

    def test_pipeline_pm_brief_structure(self) -> None:
        """PM brief has required keys after pipeline run."""
        from app.pipeline.graph import run_planning_pipeline

        result = asyncio.run(
            run_planning_pipeline(
                task_id=51,
                title="Add DATABASE_POOL_SIZE config",
                description="Allow DATABASE_POOL_SIZE env var (default 5).",
                repo_path=_THIS_REPO,
            )
        )

        assert result.get("stage") != "blocked"
        brief = result["pm_brief"]
        assert isinstance(brief.get("goals"), list)
        assert isinstance(brief.get("acceptance_criteria"), list)
        assert len(brief["acceptance_criteria"]) >= 1

    def test_pipeline_architect_impacted_files_exist(self) -> None:
        """Architect's impacted_files all exist on disk — anti-hallucination gate."""
        import os
        from app.pipeline.graph import run_planning_pipeline

        result = asyncio.run(
            run_planning_pipeline(
                task_id=52,
                title="Add structured logging to base agent",
                description="Add JSON log output via Python structlog to app/agents/base.py.",
                repo_path=_THIS_REPO,
            )
        )

        assert result.get("stage") != "blocked"
        for item in result["architect_plan"]["impacted_files"]:
            path = item["path"]
            full = os.path.join(_THIS_REPO, path)
            assert os.path.exists(full), (
                f"Architect hallucinated non-existent file: {path}"
            )

    def test_pipeline_subtasks_have_required_fields(self) -> None:
        """Every subtask from Decomposer has title, description, and type."""
        from app.pipeline.graph import run_planning_pipeline

        result = asyncio.run(
            run_planning_pipeline(
                task_id=53,
                title="Add request ID middleware to FastAPI",
                description="Add middleware that generates a UUID per request and logs it.",
                repo_path=_THIS_REPO,
            )
        )

        assert result.get("stage") != "blocked"
        subtasks = result["subtasks"]
        assert len(subtasks) >= 1
        for sub in subtasks:
            assert sub.get("title"), f"Subtask missing title: {sub}"
            assert sub.get("description"), f"Subtask missing description: {sub}"
            assert sub.get("type"), f"Subtask missing type: {sub}"

    def test_pipeline_multiple_tasks_isolated(self) -> None:
        """Two pipeline runs for different tasks produce independent results (no state bleed)."""
        from app.pipeline.graph import run_planning_pipeline

        result_a = asyncio.run(
            run_planning_pipeline(
                task_id=54,
                title="Add GET /health",
                description="Simple health endpoint.",
                repo_path=_THIS_REPO,
            )
        )
        result_b = asyncio.run(
            run_planning_pipeline(
                task_id=55,
                title="Add POST /api/tasks/:id/cancel",
                description="Cancel a task and set status to cancelled.",
                repo_path=_THIS_REPO,
            )
        )

        # Tasks must be independent — subtasks for task A should not appear in task B's results
        assert result_a.get("task_id") == 54
        assert result_b.get("task_id") == 55
        assert result_a.get("subtasks") != result_b.get("subtasks"), (
            "Two separate tasks returned identical subtasks — possible state bleed"
        )
