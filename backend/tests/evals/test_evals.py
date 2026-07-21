"""Pytest wrapper for the agent evaluation suite.

Fast tests (no LLM): schema and task file validation.
Slow tests (real LLM): run actual agents against USE_GROQ=true Groq backend.

Run slow tests explicitly:
  USE_GROQ=true GROQ_API_KEY=gsk_... pytest tests/evals/test_evals.py -m slow -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_TASKS_FILE = Path(__file__).parent / "tasks.json"

# ──────────────────────────────────────────────────────────────────────────────
# Fast tests — no LLM, just validate the eval task definitions
# ──────────────────────────────────────────────────────────────────────────────


class TestEvalTaskDefinitions:
    def test_tasks_file_exists(self) -> None:
        assert _TASKS_FILE.exists(), f"tasks.json not found at {_TASKS_FILE}"

    def test_tasks_file_valid_json(self) -> None:
        with open(_TASKS_FILE) as f:
            tasks = json.load(f)
        assert isinstance(tasks, list)

    def test_has_at_least_five_tasks(self) -> None:
        with open(_TASKS_FILE) as f:
            tasks = json.load(f)
        assert len(tasks) >= 5, f"Expected ≥5 eval tasks, got {len(tasks)}"

    def test_all_tasks_have_required_fields(self) -> None:
        with open(_TASKS_FILE) as f:
            tasks = json.load(f)
        required = {"id", "agent", "task_id", "description", "expected_fields"}
        for task in tasks:
            missing = required - set(task.keys())
            assert not missing, f"Task {task.get('id', '?')} missing fields: {missing}"

    def test_task_ids_unique(self) -> None:
        with open(_TASKS_FILE) as f:
            tasks = json.load(f)
        ids = [t["id"] for t in tasks]
        assert len(ids) == len(set(ids)), f"Duplicate task IDs: {ids}"

    def test_all_agent_names_in_registry(self) -> None:
        from app.api.specialized_agents import _REGISTRY

        with open(_TASKS_FILE) as f:
            tasks = json.load(f)
        for task in tasks:
            agent = task["agent"]
            assert (
                agent in _REGISTRY
            ), f"Eval task {task['id']} uses unknown agent '{agent}'"

    def test_eval_runner_importable(self) -> None:
        from tests.evals.eval_runner import load_tasks, run_evals, print_summary

        assert callable(load_tasks)
        assert callable(run_evals)
        assert callable(print_summary)

    def test_load_tasks_returns_list(self) -> None:
        from tests.evals.eval_runner import load_tasks

        tasks = load_tasks()
        assert isinstance(tasks, list)
        assert len(tasks) >= 5


# ──────────────────────────────────────────────────────────────────────────────
# Slow tests — require USE_GROQ=true and GROQ_API_KEY set
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.slow
class TestAgentEvals:
    """Integration tests that call real agents via Groq LLM.

    Marked slow — only run with: pytest -m slow
    Requires: USE_GROQ=true GROQ_API_KEY=gsk_...
    """

    @pytest.fixture(autouse=True)
    def require_groq(self) -> None:
        from app.config import get_settings

        settings = get_settings()
        if not settings.use_groq or not settings.groq_api_key:
            pytest.skip("USE_GROQ=true and GROQ_API_KEY required for eval tests")

    def test_sprint_planner_eval(self) -> None:
        from tests.evals.eval_runner import load_tasks, run_evals

        tasks = [t for t in load_tasks() if t["agent"] == "sprint_planner"]
        if not tasks:
            pytest.skip("No sprint_planner eval tasks found")
        results = run_evals(tasks[:1])
        r = results[0]
        assert (
            r.score >= 0.5
        ), f"Sprint planner eval score too low: {r.score:.2f}\n{r.failures}"
        assert r.tokens_in > 0, "No tokens consumed — agent may not have run"

    def test_business_analyst_eval(self) -> None:
        from tests.evals.eval_runner import load_tasks, run_evals

        tasks = [t for t in load_tasks() if t["agent"] == "business_analyst"]
        if not tasks:
            pytest.skip("No business_analyst eval tasks found")
        results = run_evals(tasks[:1])
        r = results[0]
        assert (
            r.score >= 0.5
        ), f"Business analyst eval score too low: {r.score:.2f}\n{r.failures}"

    def test_style_reviewer_eval(self) -> None:
        from tests.evals.eval_runner import load_tasks, run_evals

        tasks = [t for t in load_tasks() if t["agent"] == "style_reviewer"]
        if not tasks:
            pytest.skip("No style_reviewer eval tasks found")
        results = run_evals(tasks[:1])
        r = results[0]
        assert (
            r.score >= 0.4
        ), f"Style reviewer eval too low: {r.score:.2f}\n{r.failures}"

    def test_all_evals_pass_threshold(self) -> None:
        """Run the full eval suite and require avg score ≥ 0.6."""
        from tests.evals.eval_runner import load_tasks, run_evals

        tasks = load_tasks()
        results = run_evals(tasks)
        avg_score = sum(r.score for r in results) / len(results)
        failed = [r for r in results if r.score < 0.4]
        assert avg_score >= 0.6, (
            f"Average eval score {avg_score:.2f} < 0.60. "
            f"Failed evals: {[r.eval_id for r in failed]}"
        )
