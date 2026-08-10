"""Batch 2 audit gap-closure (§2 "Multiple agents work simultaneously
(fan-out)") — run_manager()'s subtask loop was a strict sequential
`for` loop even for subtasks with no `depends_on` edge between them
(confirmed: zero `Send()`/LangGraph fan-out usage anywhere in app/).

These tests prove `run_manager(..., enable_fanout=True)`:
1. actually runs independent subtasks CONCURRENTLY (real overlap in wall
   time, not just interleaved awaits) — the thing "fan-out" means;
2. still respects `depends_on` edges (a dependent subtask never starts
   before its dependency's wave completes);
3. serializes the git add/commit step across concurrent subtasks sharing
   one worktree (the real correctness hazard fan-out introduces — two
   concurrent `git commit` calls in the same working tree risk an
   `.git/index.lock` collision);
4. defaults to False and is behaviorally IDENTICAL to the pre-fan-out
   sequential path when not opted into (covered already by every existing
   run_manager test in this suite, which all omit `enable_fanout`).
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
import time
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


def test_topological_subtask_waves_groups_independent_subtasks() -> None:
    from app.agents.manager import _topological_subtask_waves

    # 0 and 1 are independent; 2 depends on both 0 and 1; 3 is independent
    # of everything.
    subtasks = [
        {"id": 1, "depends_on": []},
        {"id": 2, "depends_on": []},
        {"id": 3, "depends_on": [0, 1]},
        {"id": 4, "depends_on": []},
    ]
    waves = _topological_subtask_waves(subtasks)
    assert waves[0] == sorted(waves[0])
    assert set(waves[0]) == {0, 1, 3}
    assert waves[1] == [2]


def test_topological_subtask_waves_falls_back_on_cycle() -> None:
    from app.agents.manager import _topological_subtask_waves

    subtasks = [
        {"id": 1, "depends_on": [1]},
        {"id": 2, "depends_on": [0]},
    ]
    waves = _topological_subtask_waves(subtasks)
    assert waves == [[0], [1]]


def test_independent_subtasks_run_concurrently_not_sequentially(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two independent subtasks each 'take' time inside the mocked dev
    agent. Proves real concurrent overlap deterministically via an
    active/peak counter (same pattern as test_concurrency.py's own
    test_agent_run_slot_cap_3) rather than a wall-clock threshold — a
    wall-clock assertion is flaky under CPU contention from a large test
    suite running in the same process; peak-concurrency tracking isn't,
    since it only requires the two sleeps to genuinely overlap at some
    point, regardless of how long the whole run actually took."""
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.agents.reviewer import ReviewResult
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))

    task_id = 999_601
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    active: list[int] = []
    peak: list[int] = []
    lock = threading.Lock()

    def _slow_backend_dev(**kwargs: object) -> tuple[list[str], None, int, int]:
        subtask_id = int(kwargs["subtask_id"])  # type: ignore[arg-type]
        with lock:
            active.append(subtask_id)
            peak.append(len(active))
        time.sleep(0.3)
        with lock:
            active.remove(subtask_id)
        return ([], None, 10, 5)

    with (
        patch(
            "app.agents.backend_dev.run_backend_dev", side_effect=_slow_backend_dev
        ),
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
        )
        mock_reviewer.return_value = ReviewResult(verdict="approved", summary="ok")

        result = asyncio.run(
            run_manager(
                task_id=task_id,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "A", "description": "a"},
                    {"id": 2, "type": "backend", "title": "B", "description": "b"},
                ],
                worktree_path=str(worktree),
                plan="plan",
                repo_path=str(repo),
                enable_fanout=True,
            )
        )

    assert result["status"] == "completed"
    assert len(result["results"]) == 2
    assert max(peak) == 2, (
        f"expected both subtasks genuinely in flight at once (peak=2), got "
        f"peak={max(peak)} — subtasks ran sequentially instead of concurrently"
    )


def test_dependent_subtask_waits_for_its_dependency_even_with_fanout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """subtask 1 depends_on [0] — must never start before subtask 0's wave
    finishes, even with enable_fanout=True."""
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.agents.reviewer import ReviewResult
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))

    task_id = 999_602
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    start_order: list[int] = []

    def _tracking_backend_dev(**kwargs: object) -> tuple[list[str], None, int, int]:
        start_order.append(int(kwargs["subtask_id"]))  # type: ignore[arg-type]
        if kwargs["subtask_id"] == 1:
            time.sleep(0.1)
        return ([], None, 10, 5)

    with (
        patch(
            "app.agents.backend_dev.run_backend_dev",
            side_effect=_tracking_backend_dev,
        ),
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
        )
        mock_reviewer.return_value = ReviewResult(verdict="approved", summary="ok")

        result = asyncio.run(
            run_manager(
                task_id=task_id,
                subtasks=[
                    {
                        "id": 1,
                        "type": "backend",
                        "title": "A",
                        "description": "a",
                        "depends_on": [],
                    },
                    {
                        "id": 2,
                        "type": "backend",
                        "title": "B (depends on A)",
                        "description": "b",
                        "depends_on": [0],
                    },
                ],
                worktree_path=str(worktree),
                plan="plan",
                repo_path=str(repo),
                enable_fanout=True,
            )
        )

    assert result["status"] == "completed"
    # subtask_id 1 (index 0) must start before subtask_id 2 (index 1).
    assert start_order[0] == 1
    assert 2 in start_order


def test_git_commit_is_serialized_across_concurrent_subtasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real correctness hazard fan-out introduces: multiple subtasks share
    ONE worktree_path. Both mocked dev agents 'write' a file and report it
    as changed; real git_add/git_commit run against the real shared repo.
    If the git step weren't serialized, concurrent `git commit` calls
    against the same working tree risk an index.lock collision. This test
    runs 3 concurrent subtasks each producing a real file+commit and
    asserts every commit actually landed (no lock collision silently lost
    a commit) and the final commit count matches exactly what should have
    happened serially."""
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.agents.reviewer import ReviewResult
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))

    task_id = 999_603
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    def _make_dev(fname: str):
        def _dev(**kwargs: object) -> tuple[list[str], None, int, int]:
            (worktree / fname).write_text(f"content for {fname}\n")
            time.sleep(0.05)  # widen the window for a real race if unsynchronized
            return ([fname], None, 10, 5)

        return _dev

    subtasks = [
        {"id": i + 1, "type": "backend", "title": f"T{i}", "description": f"d{i}"}
        for i in range(3)
    ]

    call_count = {"n": 0}
    devs = [_make_dev(f"file{i}.txt") for i in range(3)]

    def _dispatch_dev(**kwargs: object) -> tuple[list[str], None, int, int]:
        idx = call_count["n"]
        call_count["n"] += 1
        return devs[idx % len(devs)](**kwargs)

    with (
        patch("app.agents.backend_dev.run_backend_dev", side_effect=_dispatch_dev),
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
        )
        mock_reviewer.return_value = ReviewResult(verdict="approved", summary="ok")

        result = asyncio.run(
            run_manager(
                task_id=task_id,
                subtasks=subtasks,
                worktree_path=str(worktree),
                plan="plan",
                repo_path=str(repo),
                enable_fanout=True,
            )
        )

    assert result["status"] == "completed"
    assert all(r["status"] == "completed" for r in result["results"])

    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=worktree, capture_output=True, text=True
    )
    assert log.returncode == 0
    # initial commit + 3 real subtask commits, none lost to a lock collision.
    commit_lines = [ln for ln in log.stdout.splitlines() if ln.strip()]
    assert len(commit_lines) == 4, (
        f"expected 4 commits (initial + 3 subtasks), got {len(commit_lines)}: "
        f"{log.stdout!r}"
    )
    for i in range(3):
        assert (worktree / f"file{i}.txt").exists()


def test_enable_fanout_defaults_false_and_matches_sequential_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backward-compat guarantee: omitting enable_fanout entirely must
    still dispatch strictly one-at-a-time, in _topological_subtask_order()'s
    exact order — the same contract every pre-existing run_manager test in
    this suite already relies on implicitly."""
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.agents.reviewer import ReviewResult
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "allowed_workspace_parent", str(tmp_path))

    task_id = 999_604
    repo, worktree = _init_repo_with_worktree(tmp_path, task_id)

    order: list[int] = []

    def _tracking_backend_dev(**kwargs: object) -> tuple[list[str], None, int, int]:
        order.append(int(kwargs["subtask_id"]))  # type: ignore[arg-type]
        return ([], None, 10, 5)

    with (
        patch(
            "app.agents.backend_dev.run_backend_dev",
            side_effect=_tracking_backend_dev,
        ),
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
        )
        mock_reviewer.return_value = ReviewResult(verdict="approved", summary="ok")

        result = asyncio.run(
            run_manager(
                task_id=task_id,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "A", "description": "a"},
                    {"id": 2, "type": "backend", "title": "B", "description": "b"},
                    {"id": 3, "type": "backend", "title": "C", "description": "c"},
                ],
                worktree_path=str(worktree),
                plan="plan",
                repo_path=str(repo),
                # enable_fanout omitted -> defaults False
            )
        )

    assert result["status"] == "completed"
    assert order == [1, 2, 3]
