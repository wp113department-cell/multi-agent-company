"""Gap-closure (2026-07-22, Day 14 prep) — nothing in the dev-agent path ever
committed changes to the worktree's branch (submit_patch only recorded
files_changed in a local dict, confirmed by grep before this fix). Since
worktree.get_diff() compares HEAD...branch, this meant the Reviewer agent's
own diff review has been reviewing an empty diff since Day 0. This tests
run_manager()'s new commit step against a REAL git repo + worktree — not
mocked — so the fix is verified against real git behavior, not an assumption.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import patch

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


def test_run_manager_commits_dev_agent_changes_to_real_worktree_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.agents.reviewer import ReviewResult
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))

    task_id = 999_301
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    # Simulate what a real dev agent does: write a file, but (as confirmed by
    # the gap-closure grep) never commit it — run_manager()'s new step must.
    (worktree / "feature.py").write_text("print('new feature')\n")

    with patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev, patch(
        "app.agents.qa.run_qa"
    ) as mock_qa, patch("app.agents.reviewer.run_reviewer") as mock_reviewer, patch(
        "app.repo_tools.worktree.get_diff", return_value=""
    ):
        mock_backend_dev.return_value = (["feature.py"], None)
        mock_qa.return_value = QAResult(
            status="passed",
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            typecheck_clean=True,
            lint_clean=True,
            summary="ok",
        )
        mock_reviewer.return_value = ReviewResult(verdict="approved", summary="ok")

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

    # The real assertion: the branch must have actually advanced with a real commit.
    log = subprocess.run(
        ["git", "log", f"agent/task-{task_id}", "--oneline"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert (
        "backend: Add feature" in log.stdout
    ), f"no commit landed on the branch: {log.stdout!r}"

    diff = subprocess.run(
        ["git", "diff", f"HEAD...agent/task-{task_id}"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert (
        "feature.py" in diff.stdout
    ), "get_diff()'s real query would still see an empty diff"
    assert "new feature" in diff.stdout


def test_run_manager_continues_when_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commit failure (e.g. nothing staged) must not crash the subtask —
    non-fatal, matching this file's established defensive style."""
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.agents.reviewer import ReviewResult
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))

    task_id = 999_302
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)
    # Deliberately do NOT create the file dev_agent claims to have changed —
    # git add will fail since the path doesn't exist.

    with patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev, patch(
        "app.agents.qa.run_qa"
    ) as mock_qa, patch("app.agents.reviewer.run_reviewer") as mock_reviewer, patch(
        "app.repo_tools.worktree.get_diff", return_value=""
    ):
        mock_backend_dev.return_value = (["nonexistent_file.py"], None)
        mock_qa.return_value = QAResult(
            status="passed",
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            typecheck_clean=True,
            lint_clean=True,
            summary="ok",
        )
        mock_reviewer.return_value = ReviewResult(verdict="approved", summary="ok")

        result = asyncio.run(
            run_manager(
                task_id=task_id,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "x", "description": "y"}
                ],
                worktree_path=str(worktree),
                plan="plan",
                repo_path=str(repo),
            )
        )

    # Must not crash — QA/review still ran with whatever (empty) diff resulted.
    assert result["status"] == "completed"
