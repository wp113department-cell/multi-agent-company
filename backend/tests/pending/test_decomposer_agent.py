"""Decomposer Agent live tests — require ANTHROPIC_API_KEY.

One real decomposer run is shared by every test in this file (module-scoped
fixture): the tests check different properties of the same subtask list
(live-AI plan, PENDING_TESTS_API_KEYS.md §N).
"""

from __future__ import annotations

from pathlib import Path

from typing import Any

import pytest
from tests.pending.conftest import requires_anthropic

_REPO_ROOT = str(Path(__file__).resolve().parents[3])  # repo root, not a machine path

_THIS_REPO = _REPO_ROOT

_VALID_TYPES = {"backend", "frontend", "test", "docs", "infra"}


@pytest.fixture(scope="module")
def decomposer_result() -> dict[str, Any]:
    from app.agents.decomposer import decomposer_node
    from app.pipeline.state import PipelineState

    state = PipelineState(
        task_id=20,
        task_title="Add GET /api/tasks/stats endpoint",
        task_description="Implement the feature described in the plan.",
        repo_path=_THIS_REPO,
        pm_brief={
            "goals": ["Implement the feature"],
            "constraints": ["No breaking changes"],
            "acceptance_criteria": ["Tests pass"],
            "out_of_scope": [],
        },
        architect_plan={
            "technical_approach": "Add a new route in backend/app/api/tasks.py",
            "impacted_files": [
                {"path": "backend/app/api/tasks.py", "reason": "Add new endpoint"},
                {
                    "path": "backend/tests/test_status_transitions.py",
                    "reason": "Add tests",
                },
            ],
            "risks": [{"severity": "low", "description": "Minimal impact"}],
            "risk_level": "low",
        },
        stage="decomposer",
    )
    return dict(decomposer_node(state))


@requires_anthropic
class TestDecomposerAgent:
    """Decomposer Agent: PM brief + architect plan → typed subtask list."""

    def test_decomposer_returns_subtasks(
        self, decomposer_result: dict[str, Any]
    ) -> None:
        r = decomposer_result
        assert r["stage"] != "blocked", f"Decomposer blocked: {r.get('error')}"
        assert isinstance(r.get("subtasks"), list) and len(r["subtasks"]) >= 1

    def test_decomposer_subtask_schema(self, decomposer_result: dict[str, Any]) -> None:
        assert decomposer_result["stage"] != "blocked"
        for sub in decomposer_result["subtasks"]:
            assert sub.get("title"), f"Subtask missing title: {sub}"
            assert sub.get("description"), f"Subtask missing description: {sub}"
            assert "type" in sub, f"Subtask missing type: {sub}"

    def test_decomposer_subtask_types_valid(
        self, decomposer_result: dict[str, Any]
    ) -> None:
        assert decomposer_result["stage"] != "blocked"
        for sub in decomposer_result["subtasks"]:
            assert sub.get("type", "") in _VALID_TYPES, (
                f"Decomposer produced invalid subtask type {sub.get('type')!r}. "
                f"Allowed: {_VALID_TYPES}"
            )
