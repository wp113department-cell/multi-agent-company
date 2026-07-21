"""Planner Agent live tests — require ANTHROPIC_API_KEY or Groq."""

from __future__ import annotations

import os
import re
import pytest
from tests.pending.conftest import requires_anthropic


def _make_minimal_repo(tmp_path: pytest.TempPathFactory) -> str:
    """Pre-populate a minimal FastAPI project for the planner to explore."""
    p = str(tmp_path)
    os.makedirs(os.path.join(p, "app", "api"), exist_ok=True)

    with open(os.path.join(p, "app", "main.py"), "w") as f:
        f.write(
            "from fastapi import FastAPI\n"
            "from app.api import tasks\n\n"
            "app = FastAPI()\n"
            "app.include_router(tasks.router)\n"
        )

    with open(os.path.join(p, "app", "config.py"), "w") as f:
        f.write(
            "from pydantic_settings import BaseSettings\n\n"
            "class Settings(BaseSettings):\n"
            "    database_url: str = 'sqlite:///./test.db'\n"
        )

    with open(os.path.join(p, "app", "api", "tasks.py"), "w") as f:
        f.write(
            "from fastapi import APIRouter\n\n"
            "router = APIRouter(prefix='/api/tasks')\n\n"
            "@router.get('/')\n"
            "def list_tasks():\n"
            "    return []\n"
        )

    os.makedirs(os.path.join(p, "tests"), exist_ok=True)
    with open(os.path.join(p, "tests", "test_tasks.py"), "w") as f:
        f.write("# Task tests\n")

    return p


_REQUIRED_PLAN_SECTIONS = ["## ", "Implementation Steps", "Files To Inspect"]


@requires_anthropic
class TestPlannerAgent:
    """Planner Agent: reads repo → validated markdown implementation plan."""

    def test_planner_returns_valid_plan(self, tmp_path: pytest.TempPathFactory) -> None:
        """Planner produces a plan that passes _validate_plan."""
        from app.agents.planner import run_planner, _validate_plan

        repo = _make_minimal_repo(tmp_path)  # type: ignore[arg-type]
        plan, error, *_ = run_planner(
            task_id=30,
            title="Add GET /health endpoint",
            description=(
                "Add a GET /health route to FastAPI app that returns "
                '{"status": "ok"} with HTTP 200. No auth required.'
            ),
            repo_path=repo,
        )

        assert error is None, f"Planner returned error: {error}"
        assert plan, "Planner returned empty plan"
        validation_error = _validate_plan(plan)
        assert validation_error is None, f"Plan failed validation: {validation_error}"

    def test_planner_plan_contains_required_sections(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Plan output contains required markdown sections."""
        from app.agents.planner import run_planner

        repo = _make_minimal_repo(tmp_path)  # type: ignore[arg-type]
        plan, error, *_ = run_planner(
            task_id=31,
            title="Add database pool size config",
            description="Allow DATABASE_POOL_SIZE to be set via env var (default 5).",
            repo_path=repo,
        )

        assert error is None
        for section in _REQUIRED_PLAN_SECTIONS:
            assert (
                section in plan
            ), f"Plan missing required section: '{section}'\nPlan:\n{plan[:500]}"

    def test_planner_files_to_inspect_are_real(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Every .py file in 'Files To Inspect' must exist inside the minimal repo."""
        from app.agents.planner import run_planner

        repo = _make_minimal_repo(tmp_path)  # type: ignore[arg-type]
        plan, error, *_ = run_planner(
            task_id=32,
            title="Add stats endpoint",
            description="Add GET /api/tasks/stats returning count by status in tasks.py.",
            repo_path=repo,
        )

        assert error is None
        in_section = False
        hallucinated: list[str] = []
        for line in plan.splitlines():
            if "Files To Inspect" in line:
                in_section = True
                continue
            if in_section and line.startswith("## "):
                break
            if in_section:
                for match in re.finditer(r"[\w./\-]+\.py", line):
                    rel = match.group(0).strip("`. ")
                    full = os.path.join(repo, rel)
                    if not os.path.exists(full):
                        hallucinated.append(rel)

        assert (
            not hallucinated
        ), f"Planner hallucinated non-existent files in 'Files To Inspect': {hallucinated}"

    def test_planner_plan_minimum_length(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Plan is at least 100 characters."""
        from app.agents.planner import run_planner

        repo = _make_minimal_repo(tmp_path)  # type: ignore[arg-type]
        plan, error, *_ = run_planner(
            task_id=33,
            title="Add config env var",
            description="Add an APP_ENV env var to config.py with default 'production'.",
            repo_path=repo,
        )

        assert error is None
        assert len(plan) >= 100, f"Plan too short: {len(plan)} chars"
