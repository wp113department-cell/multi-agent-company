"""Sol A19 (2026-10-12): rejecting or editing plan steps keeps every step's
dependencies pointing at the right step.

Steps are addressed by position. Rejecting an earlier step shifted the
later ones, but their depends_on indices were not renumbered, so a step
could end up depending on the wrong step or on itself, and the manager then
silently dropped the ordering. Editing depends_on was ignored, although the
refusal message told the human to do exactly that.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.manager import _topological_subtask_order
from app.pipeline.graph import SubtaskEditError, apply_subtask_edits


def _plan() -> list[dict[str, Any]]:
    return [
        {"title": "Notes", "depends_on": []},
        {"title": "Create the users table", "depends_on": []},
        {"title": "API on the users table", "depends_on": [1]},
        {"title": "UI for the API", "depends_on": [2]},
    ]


def test_rejecting_an_earlier_step_renumbers_the_rest() -> None:
    out = apply_subtask_edits(_plan(), [{"index": 0, "action": "reject"}])
    assert [s["title"] for s in out] == [
        "Create the users table",
        "API on the users table",
        "UI for the API",
    ]
    assert [s["depends_on"] for s in out] == [[], [0], [1]]
    # and the order the manager runs them in still has prerequisites first
    assert _topological_subtask_order(out) == [0, 1, 2]


def test_depends_on_can_be_edited_and_is_checked() -> None:
    out = apply_subtask_edits(
        _plan(), [{"index": 3, "action": "edit", "depends_on": [1, 2]}]
    )
    assert out[3]["depends_on"] == [1, 2]
    for bad in ([3], [9], ["1"]):
        with pytest.raises(SubtaskEditError):
            apply_subtask_edits(
                _plan(), [{"index": 3, "action": "edit", "depends_on": bad}]
            )


def test_an_edit_that_creates_a_loop_is_refused() -> None:
    with pytest.raises(SubtaskEditError, match="loop"):
        apply_subtask_edits(
            _plan(), [{"index": 1, "action": "edit", "depends_on": [3]}]
        )


def test_removing_a_dependency_then_rejecting_its_step_works() -> None:
    out = apply_subtask_edits(
        _plan(),
        [
            {"index": 2, "action": "edit", "depends_on": []},
            {"index": 1, "action": "reject"},
        ],
    )
    assert [s["title"] for s in out] == [
        "Notes",
        "API on the users table",
        "UI for the API",
    ]
    assert [s["depends_on"] for s in out] == [[], [], [1]]


def test_rejecting_a_step_others_need_is_still_refused() -> None:
    with pytest.raises(SubtaskEditError, match="still depends on it"):
        apply_subtask_edits(_plan(), [{"index": 1, "action": "reject"}])
