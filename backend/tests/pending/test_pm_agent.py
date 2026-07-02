"""PM Agent live tests — require ANTHROPIC_API_KEY."""
from __future__ import annotations

import pytest
from tests.pending.conftest import requires_anthropic


@requires_anthropic
class TestPMAgent:
    """PM Agent: task description → goals / constraints / acceptance_criteria / out_of_scope."""

    def test_pm_agent_returns_brief(self, tmp_path: pytest.TempPathFactory) -> None:
        """PM Agent submits a non-empty brief for a simple task."""
        from app.pipeline.state import PipelineState
        from app.agents.pm import pm_node

        state: PipelineState = {
            "task_id": 1,
            "task_title": "Add GET /health endpoint",
            "task_description": (
                "Add a GET /health route to the FastAPI app that returns "
                '{"status": "ok", "version": "1.0.0"} with HTTP 200.'
            ),
            "repo_path": str(tmp_path),
            "stage": "pm",
        }

        result = pm_node(state)

        assert result["stage"] != "blocked", f"PM Agent blocked: {result.get('error')}"
        assert "pm_brief" in result
        brief = result["pm_brief"]
        assert isinstance(brief.get("goals"), list) and len(brief["goals"]) >= 1
        assert isinstance(brief.get("constraints"), list)
        assert isinstance(brief.get("acceptance_criteria"), list) and len(brief["acceptance_criteria"]) >= 1
        assert isinstance(brief.get("out_of_scope"), list)

    def test_pm_agent_goals_are_non_empty_strings(self, tmp_path: pytest.TempPathFactory) -> None:
        """Every goal in the brief is a non-empty string."""
        from app.pipeline.state import PipelineState
        from app.agents.pm import pm_node

        state: PipelineState = {
            "task_id": 2,
            "task_title": "Add database connection pool config",
            "task_description": "Allow DATABASE_POOL_SIZE to be set via env var (default 5).",
            "repo_path": str(tmp_path),
            "stage": "pm",
        }

        result = pm_node(state)
        assert result["stage"] != "blocked"
        for goal in result["pm_brief"]["goals"]:
            assert isinstance(goal, str) and goal.strip(), f"Empty or non-string goal: {goal!r}"

    def test_pm_agent_acceptance_criteria_non_empty(self, tmp_path: pytest.TempPathFactory) -> None:
        """PM Agent always produces at least one acceptance criterion."""
        from app.pipeline.state import PipelineState
        from app.agents.pm import pm_node

        state: PipelineState = {
            "task_id": 3,
            "task_title": "Write pytest test for policy engine",
            "task_description": "Add a test that verifies check_path blocks .env writes.",
            "repo_path": str(tmp_path),
            "stage": "pm",
        }

        result = pm_node(state)
        assert result["stage"] != "blocked"
        assert len(result["pm_brief"]["acceptance_criteria"]) >= 1
