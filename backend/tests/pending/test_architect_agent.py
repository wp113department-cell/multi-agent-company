"""Architect Agent live tests — require ANTHROPIC_API_KEY or Groq.

One real architect run on a tiny repo is shared by every test in this file
(module-scoped fixture), instead of one paid run per test
(live-AI plan, PENDING_TESTS_API_KEYS.md §N).
"""

from __future__ import annotations

import os
from typing import Any

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


@pytest.fixture(scope="module")
def architect_result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from app.agents.architect import architect_node
    from app.pipeline.state import PipelineState

    repo = _make_minimal_repo(tmp_path_factory.mktemp("arch_repo"))  # type: ignore[arg-type]
    state = PipelineState(
        task_id=10,
        task_title="Add a new FastAPI route for task stats",
        task_description="GET /api/tasks/stats — returns count by status.",
        repo_path=repo,
        pm_brief={
            "goals": ["Implement the feature"],
            "constraints": ["No breaking changes"],
            "acceptance_criteria": ["Feature works end-to-end"],
            "out_of_scope": [],
        },
        stage="architect",
    )
    return dict(architect_node(state))


@requires_anthropic
class TestArchitectAgent:
    """Architect Agent: PM brief + codebase → impacted_files / risks / risk_level."""

    def test_architect_returns_plan(self, architect_result: dict[str, Any]) -> None:
        r = architect_result
        assert r["stage"] != "blocked", f"Architect blocked: {r.get('error')}"
        plan = r["architect_plan"]
        assert plan.get("technical_approach")
        assert isinstance(plan.get("impacted_files"), list)
        assert isinstance(plan.get("risks"), list)

    def test_architect_impacted_files_non_empty(
        self, architect_result: dict[str, Any]
    ) -> None:
        assert architect_result["stage"] != "blocked"
        files = architect_result["architect_plan"].get("impacted_files")
        assert (
            isinstance(files, list) and len(files) >= 1
        ), "Architect should propose a file"

    def test_architect_risk_level_valid(self, architect_result: dict[str, Any]) -> None:
        assert architect_result["stage"] != "blocked"
        assert architect_result["architect_plan"]["risk_level"] in (
            "low",
            "medium",
            "high",
        )
