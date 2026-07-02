"""Architect Agent live tests — require ANTHROPIC_API_KEY."""
from __future__ import annotations

import pytest
from tests.pending.conftest import requires_anthropic

_THIS_REPO = "/home/pc-117/Documents/CRR2906"


@requires_anthropic
class TestArchitectAgent:
    """Architect Agent: PM brief + codebase → impacted_files / risks / risk_level."""

    def _make_state(self, task_id: int, title: str, desc: str) -> dict:  # type: ignore[type-arg]
        from app.pipeline.state import PipelineState
        return PipelineState(
            task_id=task_id,
            task_title=title,
            task_description=desc,
            repo_path=_THIS_REPO,
            pm_brief={
                "goals": ["Implement the feature"],
                "constraints": ["No breaking changes"],
                "acceptance_criteria": ["Feature works end-to-end"],
                "out_of_scope": [],
            },
            stage="architect",
        )

    def test_architect_returns_plan(self) -> None:
        """Architect submits a plan with all required fields."""
        from app.agents.architect import architect_node

        state = self._make_state(10, "Add GET /health endpoint", "Return {status: ok}")
        result = architect_node(state)

        assert result["stage"] != "blocked", f"Architect blocked: {result.get('error')}"
        assert "architect_plan" in result
        plan = result["architect_plan"]
        assert plan.get("technical_approach")
        assert isinstance(plan.get("impacted_files"), list)
        assert isinstance(plan.get("risks"), list)
        assert plan.get("risk_level") in ("low", "medium", "high")

    def test_architect_impacted_files_exist_on_disk(self) -> None:
        """Every file path in architect_plan.impacted_files must exist in the repo."""
        import os
        from app.agents.architect import architect_node

        state = self._make_state(
            11,
            "Add a new FastAPI route for task stats",
            "GET /api/tasks/stats — returns count by status.",
        )
        result = architect_node(state)

        assert result["stage"] != "blocked"
        for item in result["architect_plan"]["impacted_files"]:
            path = item["path"]
            full = os.path.join(_THIS_REPO, path)
            assert os.path.exists(full), f"Architect hallucinated non-existent file: {path}"

    def test_architect_risk_level_valid(self) -> None:
        """risk_level is exactly one of low / medium / high."""
        from app.agents.architect import architect_node

        state = self._make_state(12, "Refactor config module", "Split config.py into sub-modules.")
        result = architect_node(state)

        assert result["stage"] != "blocked"
        assert result["architect_plan"]["risk_level"] in ("low", "medium", "high")
