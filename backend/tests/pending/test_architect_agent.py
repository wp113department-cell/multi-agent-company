"""Architect Agent live tests — require ANTHROPIC_API_KEY or Groq."""

from __future__ import annotations

import os
import pytest
from tests.pending.conftest import requires_anthropic


def _make_minimal_repo(tmp_path: pytest.TempPathFactory) -> str:
    """Create a tiny FastAPI project structure for the architect to explore."""
    p = str(tmp_path)
    os.makedirs(os.path.join(p, "app", "api"), exist_ok=True)

    # main.py
    with open(os.path.join(p, "app", "main.py"), "w") as f:
        f.write(
            "from fastapi import FastAPI\n"
            "from app.api import tasks\n\n"
            "app = FastAPI()\n"
            "app.include_router(tasks.router)\n"
        )

    # config.py
    with open(os.path.join(p, "app", "config.py"), "w") as f:
        f.write(
            "from pydantic_settings import BaseSettings\n\n"
            "class Settings(BaseSettings):\n"
            "    database_url: str = 'sqlite:///./test.db'\n"
        )

    # api/tasks.py
    with open(os.path.join(p, "app", "api", "tasks.py"), "w") as f:
        f.write(
            "from fastapi import APIRouter\n\n"
            "router = APIRouter(prefix='/api/tasks')\n\n"
            "@router.get('/')\n"
            "def list_tasks():\n"
            "    return []\n"
        )

    return p


@requires_anthropic
class TestArchitectAgent:
    """Architect Agent: PM brief + codebase → impacted_files / risks / risk_level."""

    def _make_state(self, task_id: int, title: str, desc: str, repo_path: str) -> dict:  # type: ignore[type-arg]
        from app.pipeline.state import PipelineState

        return PipelineState(
            task_id=task_id,
            task_title=title,
            task_description=desc,
            repo_path=repo_path,
            pm_brief={
                "goals": ["Implement the feature"],
                "constraints": ["No breaking changes"],
                "acceptance_criteria": ["Feature works end-to-end"],
                "out_of_scope": [],
            },
            stage="architect",
        )

    def test_architect_returns_plan(self, tmp_path: pytest.TempPathFactory) -> None:
        """Architect submits a plan with all required fields."""
        from app.agents.architect import architect_node

        repo = _make_minimal_repo(tmp_path)  # type: ignore[arg-type]
        state = self._make_state(
            10, "Add GET /health endpoint", "Return {status: ok}", repo
        )
        result = architect_node(state)

        assert result["stage"] != "blocked", f"Architect blocked: {result.get('error')}"
        assert "architect_plan" in result
        plan = result["architect_plan"]
        assert plan.get("technical_approach")
        assert isinstance(plan.get("impacted_files"), list)
        assert isinstance(plan.get("risks"), list)
        assert plan.get("risk_level") in ("low", "medium", "high")

    def test_architect_impacted_files_non_empty(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Architect proposes at least one impacted file for a route addition task."""
        from app.agents.architect import architect_node

        repo = _make_minimal_repo(tmp_path)  # type: ignore[arg-type]
        state = self._make_state(
            11,
            "Add a new FastAPI route for task stats",
            "GET /api/tasks/stats — returns count by status.",
            repo,
        )
        result = architect_node(state)

        assert result["stage"] != "blocked", f"Architect blocked: {result.get('error')}"
        plan = result["architect_plan"]
        assert isinstance(plan.get("impacted_files"), list)
        assert (
            len(plan["impacted_files"]) >= 1
        ), "Architect should propose at least one file"

    def test_architect_risk_level_valid(self, tmp_path: pytest.TempPathFactory) -> None:
        """risk_level is exactly one of low / medium / high."""
        from app.agents.architect import architect_node

        repo = _make_minimal_repo(tmp_path)  # type: ignore[arg-type]
        state = self._make_state(
            12, "Refactor config module", "Split config.py into sub-modules.", repo
        )
        result = architect_node(state)

        assert result["stage"] != "blocked", f"Architect blocked: {result.get('error')}"
        assert result["architect_plan"]["risk_level"] in ("low", "medium", "high")
