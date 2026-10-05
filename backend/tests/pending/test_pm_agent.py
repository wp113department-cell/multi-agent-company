"""PM Agent live tests — require ANTHROPIC_API_KEY.

One real PM run is shared by every test in this file (module-scoped fixture):
the tests check different fields of the same brief, so a run per test only
multiplied the paid calls (live-AI plan, PENDING_TESTS_API_KEYS.md §N).
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.pending.conftest import requires_anthropic


@pytest.fixture(scope="module")
def pm_result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from app.agents.pm import pm_node
    from app.pipeline.state import PipelineState

    state: PipelineState = {
        "task_id": 1,
        "task_title": "Add GET /health endpoint",
        "task_description": (
            "Add a GET /health route to the FastAPI app that returns "
            '{"status": "ok", "version": "1.0.0"} with HTTP 200.'
        ),
        "repo_path": str(tmp_path_factory.mktemp("pm_repo")),
        "stage": "pm",
    }
    return dict(pm_node(state))


@requires_anthropic
class TestPMAgent:
    """PM Agent: task description → goals / constraints / acceptance_criteria / out_of_scope."""

    def test_pm_agent_returns_brief(self, pm_result: dict[str, Any]) -> None:
        assert (
            pm_result["stage"] != "blocked"
        ), f"PM Agent blocked: {pm_result.get('error')}"
        brief = pm_result["pm_brief"]
        assert isinstance(brief.get("goals"), list) and len(brief["goals"]) >= 1
        assert isinstance(brief.get("constraints"), list)
        assert isinstance(brief.get("out_of_scope"), list)

    def test_pm_agent_goals_are_non_empty_strings(
        self, pm_result: dict[str, Any]
    ) -> None:
        assert pm_result["stage"] != "blocked"
        for goal in pm_result["pm_brief"]["goals"]:
            assert (
                isinstance(goal, str) and goal.strip()
            ), f"Empty or non-string goal: {goal!r}"

    def test_pm_agent_acceptance_criteria_non_empty(
        self, pm_result: dict[str, Any]
    ) -> None:
        assert pm_result["stage"] != "blocked"
        criteria = pm_result["pm_brief"]["acceptance_criteria"]
        assert isinstance(criteria, list) and len(criteria) >= 1
