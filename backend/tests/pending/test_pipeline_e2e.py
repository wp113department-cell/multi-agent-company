"""Full LangGraph pipeline E2E tests — require ANTHROPIC_API_KEY.

Live-AI plan (PENDING_TESTS_API_KEYS.md §N): one real PM → Architect →
Decomposer run is shared by the structure tests (module-scoped fixture), and
the isolation test adds exactly one more run — 2 paid pipeline runs instead
of 6. Task ids are random and high so a test run never reuses a real dev
task's pipeline checkpoint (thread_id "task-<id>" is persisted).
"""

from __future__ import annotations

import asyncio
import os
import random
from pathlib import Path
from typing import Any

import pytest
from tests.pending.conftest import requires_anthropic

_REPO_ROOT = str(Path(__file__).resolve().parents[3])  # repo root, not a machine path

_THIS_REPO = _REPO_ROOT

_BASE_ID = 2_100_000_000 + random.randrange(1_000_000) * 10


def _run(task_id: int, title: str, description: str) -> dict[str, Any]:
    from app.pipeline.graph import run_planning_pipeline

    return dict(
        asyncio.run(
            run_planning_pipeline(
                task_id=task_id,
                title=title,
                description=description,
                repo_path=_THIS_REPO,
            )
        )
    )


@pytest.fixture(scope="module")
def pipeline_result() -> dict[str, Any]:
    return _run(
        _BASE_ID + 1,
        "Add structured logging to base agent",
        "Add JSON log output via Python structlog to backend/app/agents/base.py.",
    )


@requires_anthropic
class TestPipelineE2E:
    """End-to-end: PM → Architect → Decomposer via LangGraph StateGraph."""

    def test_full_pipeline_completes(self, pipeline_result: dict[str, Any]) -> None:
        r = pipeline_result
        assert r.get("stage") != "blocked", f"Pipeline blocked: {r.get('error')}"
        assert "pm_brief" in r, "Pipeline missing pm_brief"
        assert "architect_plan" in r, "Pipeline missing architect_plan"
        assert len(r.get("subtasks") or []) >= 1, "Pipeline missing subtasks"

    def test_pipeline_pm_brief_structure(self, pipeline_result: dict[str, Any]) -> None:
        brief = pipeline_result["pm_brief"]
        assert isinstance(brief.get("goals"), list)
        assert isinstance(brief.get("acceptance_criteria"), list)
        assert len(brief["acceptance_criteria"]) >= 1

    def test_pipeline_architect_impacted_files_exist(
        self, pipeline_result: dict[str, Any]
    ) -> None:
        """Anti-hallucination: the file the task names is listed, and every
        listed path is either a real file or a new file in a real folder."""
        paths = [i["path"] for i in pipeline_result["architect_plan"]["impacted_files"]]
        assert any(p.endswith("app/agents/base.py") for p in paths), paths
        for p in paths:
            full = os.path.join(_THIS_REPO, p)
            assert os.path.exists(full) or os.path.isdir(
                os.path.dirname(full)
            ), f"Architect hallucinated a path in a non-existent folder: {p}"

    def test_pipeline_subtasks_have_required_fields(
        self, pipeline_result: dict[str, Any]
    ) -> None:
        for sub in pipeline_result["subtasks"]:
            assert sub.get("title"), f"Subtask missing title: {sub}"
            assert sub.get("description"), f"Subtask missing description: {sub}"
            assert sub.get("type"), f"Subtask missing type: {sub}"

    def test_pipeline_multiple_tasks_isolated(
        self, pipeline_result: dict[str, Any]
    ) -> None:
        """A second, different task gets its own independent result (no state bleed)."""
        other = _run(
            _BASE_ID + 2,
            "Add POST /api/tasks/{id}/cancel",
            "Cancel a task and set its status to cancelled.",
        )
        assert (
            other.get("stage") != "blocked"
        ), f"Pipeline blocked: {other.get('error')}"
        assert pipeline_result.get("task_id") == _BASE_ID + 1
        assert other.get("task_id") == _BASE_ID + 2
        assert other.get("subtasks") != pipeline_result.get("subtasks")
