"""Planner Agent live tests — require ANTHROPIC_API_KEY."""
from __future__ import annotations

import pytest
from tests.pending.conftest import requires_anthropic

_THIS_REPO = "/home/pc-117/Documents/CRR2906"

_REQUIRED_PLAN_SECTIONS = ["## ", "Implementation Steps", "Files To Inspect"]


@requires_anthropic
class TestPlannerAgent:
    """Planner Agent: reads repo → validated markdown implementation plan."""

    def test_planner_returns_valid_plan(self) -> None:
        """Planner produces a plan that passes _validate_plan."""
        from app.agents.planner import run_planner, _validate_plan

        plan, error = run_planner(
            task_id=30,
            title="Add GET /health endpoint",
            description=(
                "Add a GET /health route to FastAPI app that returns "
                '{"status": "ok"} with HTTP 200. No auth required.'
            ),
            repo_path=_THIS_REPO,
        )

        assert error is None, f"Planner returned error: {error}"
        assert plan, "Planner returned empty plan"
        validation_error = _validate_plan(plan)
        assert validation_error is None, f"Plan failed validation: {validation_error}"

    def test_planner_plan_contains_required_sections(self) -> None:
        """Plan output contains required markdown sections."""
        from app.agents.planner import run_planner

        plan, error = run_planner(
            task_id=31,
            title="Add DATABASE_POOL_SIZE config",
            description="Allow DATABASE_POOL_SIZE to be set via env var (default 5).",
            repo_path=_THIS_REPO,
        )

        assert error is None
        for section in _REQUIRED_PLAN_SECTIONS:
            assert section in plan, f"Plan missing required section: '{section}'\nPlan:\n{plan[:500]}"

    def test_planner_files_to_inspect_are_real(self) -> None:
        """Every file path in 'Files To Inspect' section must exist on disk."""
        import os
        import re
        from app.agents.planner import run_planner

        plan, error = run_planner(
            task_id=32,
            title="Add policy test for secrets/ path",
            description="Add a pytest test to test_policy.py asserting check_path blocks secrets/key.txt.",
            repo_path=_THIS_REPO,
        )

        assert error is None
        # Extract file paths from the plan (lines that look like file paths after Files To Inspect)
        in_section = False
        hallucinated: list[str] = []
        for line in plan.splitlines():
            if "Files To Inspect" in line:
                in_section = True
                continue
            if in_section and line.startswith("## "):
                break  # next section
            if in_section:
                # Grab anything that looks like a relative path: word/word.py
                for match in re.finditer(r"[\w./\-]+\.py", line):
                    rel = match.group(0).strip("`. ")
                    full = os.path.join(_THIS_REPO, rel)
                    if not os.path.exists(full):
                        hallucinated.append(rel)

        assert not hallucinated, (
            f"Planner hallucinated non-existent files in 'Files To Inspect': {hallucinated}"
        )

    def test_planner_plan_minimum_length(self) -> None:
        """Plan is at least 100 characters."""
        from app.agents.planner import run_planner

        plan, error = run_planner(
            task_id=33,
            title="Update model_router default to Haiku",
            description="Change default MODEL_ROUTER value in config.py to claude-haiku-4-5-20251001.",
            repo_path=_THIS_REPO,
        )

        assert error is None
        assert len(plan) >= 100, f"Plan too short: {len(plan)} chars"
