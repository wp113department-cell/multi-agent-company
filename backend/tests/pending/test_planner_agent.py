"""Planner Agent live tests — require ANTHROPIC_API_KEY or Groq.

One real planner run is shared by every test in this file (module-scoped
fixture) instead of one paid run per test (live-AI plan,
PENDING_TESTS_API_KEYS.md §N).
"""

from __future__ import annotations

import os
import re
from typing import Any

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


# roles/planner.md v2 section names (the files section is "Files Read").
_REQUIRED_PLAN_SECTIONS = ["## ", "Implementation Steps", "Files Read"]


@pytest.fixture(scope="module")
def planner_run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from app.agents.planner import run_planner

    repo = _make_minimal_repo(tmp_path_factory.mktemp("planner_repo"))  # type: ignore[arg-type]
    plan, error, *_ = run_planner(
        task_id=30,
        title="Add task stats endpoint",
        description="Add GET /api/tasks/stats returning count by status in tasks.py.",
        repo_path=repo,
    )
    return {"plan": plan or "", "error": error, "repo": repo}


@requires_anthropic
class TestPlannerAgent:
    """Planner Agent: reads repo → validated markdown implementation plan."""

    def test_planner_returns_valid_plan(self, planner_run: dict[str, Any]) -> None:
        from app.agents.planner import _validate_plan

        assert (
            planner_run["error"] is None
        ), f"Planner returned error: {planner_run['error']}"
        assert planner_run["plan"], "Planner returned empty plan"
        assert _validate_plan(planner_run["plan"]) is None

    def test_planner_plan_contains_required_sections(
        self, planner_run: dict[str, Any]
    ) -> None:
        assert planner_run["error"] is None
        for section in _REQUIRED_PLAN_SECTIONS:
            assert section in planner_run["plan"], f"Plan missing section {section!r}"

    def test_planner_files_to_inspect_are_real(
        self, planner_run: dict[str, Any]
    ) -> None:
        """Every .py file in 'Files Read' must exist inside the minimal repo."""
        assert planner_run["error"] is None
        in_section = False
        hallucinated: list[str] = []
        for line in planner_run["plan"].splitlines():
            if "Files Read" in line:
                in_section = True
                continue
            if in_section and line.startswith("## "):
                break
            if in_section:
                for match in re.finditer(r"[\w./\-]+\.py", line):
                    rel = match.group(0).strip("`. ")
                    if not os.path.exists(os.path.join(planner_run["repo"], rel)):
                        hallucinated.append(rel)
        assert not hallucinated, f"Planner listed non-existent files: {hallucinated}"

    def test_planner_plan_minimum_length(self, planner_run: dict[str, Any]) -> None:
        assert planner_run["error"] is None
        assert (
            len(planner_run["plan"]) >= 100
        ), f"Plan too short: {len(planner_run['plan'])}"
