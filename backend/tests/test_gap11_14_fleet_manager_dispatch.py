"""Gap-closure Days 11-14 (Stage 1.1, answers.md) — proves
FleetManager.select()'s output is now the real dispatch decision in
app.agents.manager.run_manager(), not the discarded side-channel it was
before (Day 12 Part 4's own comment: "additive instrumentation only, does
not change which function runs"). app/fleet/fleet_manager.py's own module
docstring names this exact gap: "manager.py dispatches by hardcoded subtask
type strings... Fleet Manager makes dispatch a data-driven query."

Reuses test_manager_git_commit.py's real-git-repo-plus-worktree convention
(not mocked) for run_manager()'s surrounding infrastructure, isolating the
mock to exactly the two things under test: FleetManager.select() and the
two candidate dev-agent functions.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _run_git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"


def _init_repo_with_worktree(tmp_path: Path, task_id: int) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(["init", "-q"], cwd=repo)
    _run_git(["config", "user.email", "test@test.com"], cwd=repo)
    _run_git(["config", "user.name", "Test User"], cwd=repo)
    (repo / "README.md").write_text("hello\n")
    _run_git(["add", "README.md"], cwd=repo)
    _run_git(["commit", "-q", "-m", "initial commit"], cwd=repo)

    branch = f"agent/task-{task_id}"
    worktree = tmp_path / f"wt-{task_id}"
    _run_git(["worktree", "add", "-q", "-b", branch, str(worktree)], cwd=repo)
    return repo, worktree


def _fake_plan(agent_name: str) -> MagicMock:
    plan = MagicMock()
    plan.agent_name = agent_name
    return plan


def test_select_overriding_the_subtask_type_default_is_what_actually_dispatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The subtask is type='backend' (the old code would always call
    run_backend_dev for this), but FleetManager.select() is mocked to
    return agent_name='frontend_dev' — a deliberate disagreement. If
    select()'s output is genuinely the dispatch decision, run_frontend_dev
    must be the one actually called, not run_backend_dev."""
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.agents.reviewer import ReviewResult
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))

    task_id = 999_401
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    with (
        patch("app.fleet.fleet_manager.get_fleet_manager") as mock_get_fleet_manager,
        patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev,
        patch("app.agents.frontend_dev.run_frontend_dev") as mock_frontend_dev,
        patch("app.agents.qa.run_qa") as mock_qa,
        patch("app.agents.reviewer.run_reviewer") as mock_reviewer,
        patch("app.repo_tools.worktree.get_diff", return_value=""),
    ):
        mock_get_fleet_manager.return_value.select.return_value = _fake_plan(
            "frontend_dev"
        )
        mock_frontend_dev.return_value = (["feature.py"], None, 100, 50)
        mock_qa.return_value = QAResult(
            status="passed",
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            typecheck_clean=True,
            lint_clean=True,
            summary="ok",
            tokens_in=20,
            tokens_out=10,
        )
        mock_reviewer.return_value = ReviewResult(
            verdict="approved", summary="ok", tokens_in=15, tokens_out=5
        )

        asyncio.run(
            run_manager(
                task_id=task_id,
                subtasks=[
                    {
                        "id": 1,
                        "type": "backend",
                        "title": "Add feature",
                        "description": "...",
                    }
                ],
                worktree_path=str(worktree),
                plan="Add a feature",
                repo_path=str(repo),
            )
        )

    mock_frontend_dev.assert_called_once()
    mock_backend_dev.assert_not_called()


def test_select_unavailable_falls_back_to_subtask_type_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FleetManager.select() raising (registry unavailable, etc.) must never
    block a subtask — dispatch falls back to the pre-existing subtask_type
    heuristic, matching the file's own no-raise-past-this-function
    convention for the scheduler's own health."""
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.agents.reviewer import ReviewResult
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))

    task_id = 999_402
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    with (
        patch(
            "app.fleet.fleet_manager.get_fleet_manager",
            side_effect=RuntimeError("registry unavailable"),
        ),
        patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev,
        patch("app.agents.frontend_dev.run_frontend_dev") as mock_frontend_dev,
        patch("app.agents.qa.run_qa") as mock_qa,
        patch("app.agents.reviewer.run_reviewer") as mock_reviewer,
        patch("app.repo_tools.worktree.get_diff", return_value=""),
    ):
        mock_backend_dev.return_value = (["feature.py"], None, 100, 50)
        mock_qa.return_value = QAResult(
            status="passed",
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            typecheck_clean=True,
            lint_clean=True,
            summary="ok",
            tokens_in=20,
            tokens_out=10,
        )
        mock_reviewer.return_value = ReviewResult(
            verdict="approved", summary="ok", tokens_in=15, tokens_out=5
        )

        result = asyncio.run(
            run_manager(
                task_id=task_id,
                subtasks=[
                    {
                        "id": 1,
                        "type": "backend",
                        "title": "Add feature",
                        "description": "...",
                    }
                ],
                worktree_path=str(worktree),
                plan="Add a feature",
                repo_path=str(repo),
            )
        )

    assert result["status"] == "completed"
    mock_backend_dev.assert_called_once()
    mock_frontend_dev.assert_not_called()
