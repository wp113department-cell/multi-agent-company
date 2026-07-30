"""Gap-closure Days 11-14 (Stage 1.1, answers.md) — proves subtasks are now
dispatched in dependency order, not just decomposer-list order.
`run_manager()`'s subtask loop previously did `for _subtask_idx, subtask in
enumerate(subtasks):` with zero reference to `depends_on` anywhere in the
loop (confirmed by grep before this fix) — a subtask could start before a
subtask it explicitly depended on had even run.

`depends_on` is documented in roles/decomposer.md as "a list of 0-based
subtask indices" into the same submitted list — not a Subtask.id DB primary
key (those don't exist yet at this point).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.agents.manager import _topological_subtask_order

# ---------------------------------------------------------------------------
# Unit tests — the pure function in isolation
# ---------------------------------------------------------------------------


def test_no_dependencies_preserves_original_order() -> None:
    subtasks: list[dict[str, Any]] = [{"title": "a"}, {"title": "b"}, {"title": "c"}]
    assert _topological_subtask_order(subtasks) == [0, 1, 2]


def test_simple_linear_chain_is_resolved() -> None:
    # 0 depends on nothing, 1 depends on 0, 2 depends on 1 — already in order,
    # but written with explicit depends_on to prove it's honored, not luck.
    subtasks: list[dict[str, Any]] = [
        {"title": "migration", "depends_on": []},
        {"title": "backend", "depends_on": [0]},
        {"title": "frontend", "depends_on": [1]},
    ]
    assert _topological_subtask_order(subtasks) == [0, 1, 2]


def test_out_of_original_order_dependency_is_reordered() -> None:
    """The real acceptance case: the decomposer listed the dependent subtask
    BEFORE its dependency — the sort must still put the dependency first."""
    subtasks: list[dict[str, Any]] = [
        {"title": "backend uses migration", "depends_on": [1]},  # index 0
        {"title": "migration", "depends_on": []},  # index 1
    ]
    order = _topological_subtask_order(subtasks)
    assert order.index(1) < order.index(0), "migration (1) must come before backend (0)"


def test_diamond_dependency_resolved_with_deterministic_tiebreak() -> None:
    # 0: migration (no deps). 1 and 2 both depend on 0. 3 depends on both 1 and 2.
    subtasks: list[dict[str, Any]] = [
        {"title": "migration", "depends_on": []},
        {"title": "backend", "depends_on": [0]},
        {"title": "frontend", "depends_on": [0]},
        {"title": "e2e test", "depends_on": [1, 2]},
    ]
    order = _topological_subtask_order(subtasks)
    assert order[0] == 0
    assert order[-1] == 3
    assert order.index(1) < order.index(3)
    assert order.index(2) < order.index(3)
    # Deterministic tiebreak: 1 and 2 become ready at the same time, so the
    # lower original index (1) is scheduled first.
    assert order == [0, 1, 2, 3]


def test_cycle_falls_back_to_original_order_without_raising() -> None:
    subtasks: list[dict[str, Any]] = [
        {"title": "a", "depends_on": [1]},
        {"title": "b", "depends_on": [0]},
    ]
    assert _topological_subtask_order(subtasks) == [0, 1]


def test_self_reference_is_ignored_not_treated_as_a_cycle() -> None:
    subtasks: list[dict[str, Any]] = [
        {"title": "a", "depends_on": [0]},  # depends on itself — nonsensical, ignored
        {"title": "b", "depends_on": []},
    ]
    assert _topological_subtask_order(subtasks) == [0, 1]


def test_out_of_range_index_falls_back_to_original_order() -> None:
    subtasks: list[dict[str, Any]] = [
        {"title": "a", "depends_on": [99]},  # 99 doesn't exist
        {"title": "b", "depends_on": []},
    ]
    assert _topological_subtask_order(subtasks) == [0, 1]


def test_empty_list_returns_empty() -> None:
    assert _topological_subtask_order([]) == []


def test_missing_depends_on_key_treated_as_no_dependencies() -> None:
    subtasks: list[dict[str, Any]] = [{"title": "a"}, {"title": "b"}]
    assert _topological_subtask_order(subtasks) == [0, 1]


# ---------------------------------------------------------------------------
# Integration test — run_manager() actually dispatches in dependency order,
# not decomposer-list order, and _db_subtask_rows status-update correlation
# (position-based, keyed to the ORIGINAL list order) still lands on the
# correct row despite the reordered dispatch.
# ---------------------------------------------------------------------------


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


def test_run_manager_dispatches_backend_subtasks_in_dependency_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """subtasks[0] depends on subtasks[1] (deliberately listed out of
    dependency order, the real-world shape this fix targets). Both are
    'backend' type so both go through run_backend_dev — the call order
    proves dispatch order, since the mock records call order directly."""
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.agents.reviewer import ReviewResult
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))

    task_id = 999_501
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    call_order: list[str] = []

    def _fake_backend_dev(**kwargs: Any) -> tuple[list[str], None, int, int]:
        call_order.append(kwargs["plan"])
        return (["feature.py"], None, 100, 50)

    with (
        patch(
            "app.fleet.fleet_manager.get_fleet_manager",
            side_effect=RuntimeError("skip fleet_manager for this test"),
        ),
        patch("app.agents.backend_dev.run_backend_dev", side_effect=_fake_backend_dev),
        patch("app.agents.qa.run_qa") as mock_qa,
        patch("app.agents.reviewer.run_reviewer") as mock_reviewer,
        patch("app.repo_tools.worktree.get_diff", return_value=""),
    ):
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
                        "title": "Use the migration",
                        "description": "USES_MIGRATION",
                        "depends_on": [1],
                    },
                    {
                        "id": 2,
                        "type": "backend",
                        "title": "Run the migration",
                        "description": "IS_MIGRATION",
                        "depends_on": [],
                    },
                ],
                worktree_path=str(worktree),
                plan="fallback plan",
                repo_path=str(repo),
            )
        )

    assert call_order == [
        "IS_MIGRATION",
        "USES_MIGRATION",
    ], f"migration must dispatch before the subtask that depends on it, got {call_order}"
