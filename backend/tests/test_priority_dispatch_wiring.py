"""Batch 2 audit gap-closure (§2 "Priorities managed") — proves
run_manager() actually reads the real DevTask.priority column and threads
it into subtask_slot()/agent_run_slot() (app/pipeline/concurrency.py's
PrioritySemaphore-backed slots), instead of the field being stored and
read back into API responses but consulted by nothing, as the audit found.

Isolates the mock to exactly the two things under test — app.db.repository.
get_task (so no real Postgres connection is needed) and the concurrency
slot functions themselves (to capture the priority kwarg they were called
with) — reusing test_manager_git_commit.py's real-git-repo-plus-worktree
convention for run_manager()'s surrounding infrastructure.
"""

from __future__ import annotations

import asyncio
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

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


def test_devtask_priority_is_threaded_into_concurrency_slots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.agents.reviewer import ReviewResult
    from app.config import get_settings
    from app.pipeline.concurrency import agent_run_slot as real_agent_run_slot
    from app.pipeline.concurrency import subtask_slot as real_subtask_slot

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))

    task_id = 999_501
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    fake_task = MagicMock()
    fake_task.priority = "high"

    seen_agent_run_priorities: list[str] = []
    seen_subtask_priorities: list[str] = []

    @asynccontextmanager
    async def _spy_agent_run_slot(priority: str = "medium") -> AsyncIterator[None]:
        seen_agent_run_priorities.append(priority)
        async with real_agent_run_slot(priority=priority):
            yield

    def _spy_subtask_slot(epic_id: str, priority: str = "medium"):
        seen_subtask_priorities.append(priority)
        return real_subtask_slot(epic_id, priority=priority)

    with (
        patch("app.db.repository.get_task", new=AsyncMock(return_value=fake_task)),
        patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev,
        patch("app.agents.qa.run_qa") as mock_qa,
        patch("app.agents.reviewer.run_reviewer") as mock_reviewer,
        patch("app.repo_tools.worktree.get_diff", return_value=""),
        patch("app.pipeline.concurrency.agent_run_slot", _spy_agent_run_slot),
        patch("app.pipeline.concurrency.subtask_slot", _spy_subtask_slot),
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
                db=AsyncMock(),  # any non-None session — get_task is mocked above
            )
        )

    assert result["status"] == "completed"
    assert seen_subtask_priorities == ["high"]
    # dev, qa, and reviewer each acquire their own agent_run_slot — all 3
    # must carry the task's real priority, not the "medium" default.
    assert seen_agent_run_priorities == ["high", "high", "high"]


def test_no_db_defaults_to_medium_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserves every existing caller's behavior: without a db session,
    task_priority stays 'medium' — identical to plain FIFO, exactly what
    every real call site got before this fix."""
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.agents.reviewer import ReviewResult
    from app.config import get_settings
    from app.pipeline.concurrency import subtask_slot as real_subtask_slot

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))

    task_id = 999_502
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    seen_subtask_priorities: list[str] = []

    def _spy_subtask_slot(epic_id: str, priority: str = "medium"):
        seen_subtask_priorities.append(priority)
        return real_subtask_slot(epic_id, priority=priority)

    with (
        patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev,
        patch("app.agents.qa.run_qa") as mock_qa,
        patch("app.agents.reviewer.run_reviewer") as mock_reviewer,
        patch("app.repo_tools.worktree.get_diff", return_value=""),
        patch("app.pipeline.concurrency.subtask_slot", _spy_subtask_slot),
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
                # db omitted -> None, matching every pre-existing caller that
                # never passed one.
            )
        )

    assert result["status"] == "completed"
    assert seen_subtask_priorities == ["medium"]
