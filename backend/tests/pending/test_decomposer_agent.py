"""Decomposer Agent live tests — require ANTHROPIC_API_KEY."""

from __future__ import annotations

from tests.pending.conftest import requires_anthropic

_THIS_REPO = "/home/pc-117/Documents/CRR2906"

_VALID_TYPES = {"backend", "frontend", "test", "docs", "infra"}


@requires_anthropic
class TestDecomposerAgent:
    """Decomposer Agent: PM brief + architect plan → typed subtask list."""

    def _make_state(self, task_id: int, title: str) -> dict:  # type: ignore[type-arg]
        from app.pipeline.state import PipelineState

        return PipelineState(
            task_id=task_id,
            task_title=title,
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

    def test_decomposer_returns_subtasks(self) -> None:
        """Decomposer returns a non-empty list of subtasks."""
        from app.agents.decomposer import decomposer_node

        state = self._make_state(20, "Add GET /health endpoint")
        result = decomposer_node(state)

        assert (
            result["stage"] != "blocked"
        ), f"Decomposer blocked: {result.get('error')}"
        assert "subtasks" in result
        assert isinstance(result["subtasks"], list)
        assert len(result["subtasks"]) >= 1

    def test_decomposer_subtask_schema(self) -> None:
        """Every subtask has required fields: type, title, description."""
        from app.agents.decomposer import decomposer_node

        state = self._make_state(21, "Add pagination to GET /api/tasks")
        result = decomposer_node(state)

        assert result["stage"] != "blocked"
        for sub in result["subtasks"]:
            assert "title" in sub and sub["title"], f"Subtask missing title: {sub}"
            assert (
                "description" in sub and sub["description"]
            ), f"Subtask missing description: {sub}"
            assert "type" in sub, f"Subtask missing type: {sub}"

    def test_decomposer_subtask_types_valid(self) -> None:
        """All subtask type values are within the allowed set."""
        from app.agents.decomposer import decomposer_node

        state = self._make_state(22, "Add logging to Coder Agent")
        result = decomposer_node(state)

        assert result["stage"] != "blocked"
        for sub in result["subtasks"]:
            sub_type = sub.get("type", "")
            assert sub_type in _VALID_TYPES, (
                f"Decomposer produced invalid subtask type '{sub_type}'. "
                f"Allowed: {_VALID_TYPES}"
            )
