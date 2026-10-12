"""Sol A20 (2026-10-12, owner choice "only clash-free steps in parallel"):
parallel task steps share one worktree, so they run together only when the
files they will edit do not overlap. Before, every independent step ran at
once, and two steps editing the same file (or one running tests while
another was mid-edit) could clash.
"""

from __future__ import annotations

from typing import Any

from app.agents.manager import _topological_subtask_waves


def _step(files: list[str] | None, deps: list[int] | None = None) -> dict[str, Any]:
    step: dict[str, Any] = {"depends_on": deps or []}
    if files is not None:
        step["files_to_edit"] = files
    return step


def test_steps_editing_different_files_still_run_together() -> None:
    waves = _topological_subtask_waves(
        [_step(["api/users.py"]), _step(["web/users.tsx"]), _step(["docs/users.md"])]
    )
    assert waves == [[0, 1, 2]]


def test_steps_editing_the_same_file_take_turns() -> None:
    waves = _topological_subtask_waves(
        [
            _step(["api/users.py"]),
            _step(["./api/users.py", "api/x.py"]),
            _step(["b.py"]),
        ]
    )
    assert waves == [[0, 2], [1]]


def test_a_folder_overlaps_the_files_inside_it() -> None:
    waves = _topological_subtask_waves([_step(["api/"]), _step(["api/users.py"])])
    assert waves == [[0], [1]]


def test_a_step_that_does_not_say_what_it_edits_runs_alone() -> None:
    waves = _topological_subtask_waves([_step(None), _step(["a.py"]), _step([])])
    assert waves == [[0], [1], [2]]


def test_dependencies_are_still_respected() -> None:
    waves = _topological_subtask_waves(
        [_step(["a.py"]), _step(["a.py"]), _step(["c.py"], deps=[0, 1])]
    )
    order = [i for wave in waves for i in wave]
    assert order.index(2) > order.index(0) and order.index(2) > order.index(1)
    assert waves == [[0], [1], [2]]
