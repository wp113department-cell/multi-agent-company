"""#227 (2026-09-28, GRIDIRON_PARTIAL "Take over a task / edit plan /
reject one step and resume exactly there") — unit tests for
apply_subtask_edits(), the pure, position-based edit/reject engine at the
core of this item's real, bounded slice (see app/pipeline/graph.py's own
module-level docstring on that function for the deliberate scoping
decision vs. the audit's full "graph-topology change" ask).
"""

from __future__ import annotations

import pytest

from app.pipeline.graph import SubtaskEditError, apply_subtask_edits


def _subtasks() -> list[dict]:
    return [
        {"type": "backend", "title": "Add model", "description": "d0"},
        {
            "type": "backend",
            "title": "Add endpoint",
            "description": "d1",
            "depends_on": [0],
        },
        {"type": "frontend", "title": "Add UI", "description": "d2", "depends_on": [1]},
    ]


def test_no_edits_returns_the_same_subtasks_unchanged() -> None:
    subtasks = _subtasks()
    result = apply_subtask_edits(subtasks, None)
    assert result == subtasks
    result2 = apply_subtask_edits(subtasks, [])
    assert result2 == subtasks


def test_edit_overlays_given_fields_by_position() -> None:
    subtasks = _subtasks()
    result = apply_subtask_edits(
        subtasks, [{"index": 1, "action": "edit", "title": "Add POST endpoint"}]
    )
    assert result[1]["title"] == "Add POST endpoint"
    assert result[1]["description"] == "d1"  # untouched field preserved
    assert result[0] == subtasks[0]  # other subtasks unaffected
    assert result[2] == subtasks[2]


def test_edit_does_not_mutate_the_original_list() -> None:
    subtasks = _subtasks()
    original_title = subtasks[1]["title"]
    apply_subtask_edits(subtasks, [{"index": 1, "action": "edit", "title": "changed"}])
    assert subtasks[1]["title"] == original_title


def test_reject_removes_a_leaf_subtask_with_no_dependents() -> None:
    subtasks = _subtasks()
    result = apply_subtask_edits(subtasks, [{"index": 2, "action": "reject"}])
    assert len(result) == 2
    assert [s["title"] for s in result] == ["Add model", "Add endpoint"]


def test_reject_refuses_when_a_remaining_subtask_still_depends_on_it() -> None:
    subtasks = _subtasks()
    with pytest.raises(SubtaskEditError, match="still depends on it"):
        apply_subtask_edits(subtasks, [{"index": 0, "action": "reject"}])


def test_rejecting_both_a_step_and_its_dependent_together_is_allowed() -> None:
    """Rejecting index 1 AND index 2 (the only thing depending on 1) in
    the SAME request is safe — no remaining subtask references either."""
    subtasks = _subtasks()
    result = apply_subtask_edits(
        subtasks,
        [
            {"index": 1, "action": "reject"},
            {"index": 2, "action": "reject"},
        ],
    )
    assert len(result) == 1
    assert result[0]["title"] == "Add model"


def test_out_of_range_index_is_rejected() -> None:
    subtasks = _subtasks()
    with pytest.raises(SubtaskEditError, match="out of range"):
        apply_subtask_edits(subtasks, [{"index": 99, "action": "edit", "title": "x"}])


def test_negative_index_is_rejected() -> None:
    subtasks = _subtasks()
    with pytest.raises(SubtaskEditError, match="out of range"):
        apply_subtask_edits(subtasks, [{"index": -1, "action": "reject"}])


def test_unknown_action_is_rejected() -> None:
    subtasks = _subtasks()
    with pytest.raises(SubtaskEditError, match="unknown subtask edit action"):
        apply_subtask_edits(subtasks, [{"index": 0, "action": "delete_forever"}])


def test_edit_and_reject_combined_in_one_request() -> None:
    subtasks = _subtasks()
    result = apply_subtask_edits(
        subtasks,
        [
            {"index": 0, "action": "edit", "description": "new description"},
            {"index": 2, "action": "reject"},
        ],
    )
    assert len(result) == 2
    assert result[0]["description"] == "new description"
    assert result[1]["title"] == "Add endpoint"
