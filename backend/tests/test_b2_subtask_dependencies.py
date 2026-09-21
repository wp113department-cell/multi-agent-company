"""Verification batch B2, item #48 (dependencies managed).

Valid graphs order correctly (confirmed); found: an out-of-range / self / non-integer
`depends_on` entry was silently DROPPED, so the subtask lost its constraint — under
fan-out it was dispatched in the SAME parallel wave as the thing it depends on —
although both functions' docstrings promise a sequential fallback for a malformed graph.
"""

from __future__ import annotations

import logging
import random

import pytest

from app.agents.manager import (
    _subtask_dependencies,
    _topological_subtask_order as order,
    _topological_subtask_waves as waves,
)


def st(*deps):
    return {"type": "backend", "title": "t", "depends_on": list(deps)}


@pytest.mark.parametrize(
    "subtasks, exp_order, exp_waves",
    [
        ([st(), st(0), st(1)], [0, 1, 2], [[0], [1], [2]]),
        ([st(), st(0), st(0), st(1, 2)], [0, 1, 2, 3], [[0], [1, 2], [3]]),
        ([st(), st(), st()], [0, 1, 2], [[0, 1, 2]]),
        ([st(2), st(), st(1)], [1, 2, 0], [[1], [2], [0]]),  # dependency listed later
        ([st(), st(0, 0, 0)], [0, 1], [[0], [1]]),  # duplicate edges
        ([], [], []),
        ([st(), {"type": "b", "title": "x", "depends_on": None}], [0, 1], [[0, 1]]),
    ],
)
def test_valid_graphs(subtasks, exp_order, exp_waves) -> None:
    assert order(subtasks) == exp_order
    assert waves(subtasks) == exp_waves


@pytest.mark.parametrize(
    "subtasks",
    [
        [st(1), st(0)],  # cycle
        [st(0)],  # self dependency
        [st(9), st()],  # out of range
        [st(-1), st()],  # negative
        [
            st(),
            {"type": "b", "title": "x", "depends_on": ["0"]},
        ],  # LLM gave a string index
        [
            {"title": "A", "depends_on": []},
            {"title": "B", "depends_on": ["A"]},
        ],  # titles
        [
            st(),
            {"type": "b", "title": "x", "depends_on": [True]},
        ],  # bool is an int subclass
    ],
)
def test_malformed_graphs_fall_back_to_sequential_never_parallel(
    subtasks, caplog
) -> None:
    n = len(subtasks)
    with caplog.at_level(logging.WARNING, logger="app.agents.manager"):
        assert order(subtasks) == list(range(n))
        assert waves(subtasks) == [
            [i] for i in range(n)
        ], "a subtask with an unresolvable dependency must not share a parallel wave"
    assert any("depends_on" in r.getMessage() for r in caplog.records)


def test_invalid_entries_are_counted() -> None:
    deps, invalid = _subtask_dependencies([st(0, 5, "x"), st(0)])
    assert deps == [[], [0]] and invalid == 3


def test_random_dags_are_ordered_and_waved_correctly() -> None:
    rng = random.Random(1234)
    for _ in range(300):
        n = rng.randint(1, 14)
        subtasks = []
        for i in range(n):
            k = rng.randint(0, min(i, 3))
            subtasks.append(
                st(*sorted(rng.sample(range(i), k)))
            )  # deps only on earlier
        perm = list(range(n))
        rng.shuffle(perm)  # renumber so dependencies are NOT already in list order
        pos = {old: new for new, old in enumerate(perm)}
        shuffled = [None] * n
        for old, task in enumerate(subtasks):
            shuffled[pos[old]] = st(*[pos[d] for d in task["depends_on"]])
        o = order(shuffled)
        assert sorted(o) == list(range(n))
        rank = {idx: r for r, idx in enumerate(o)}
        w = waves(shuffled)
        wave_of = {idx: k for k, wv in enumerate(w) for idx in wv}
        for i, task in enumerate(shuffled):
            for d in task["depends_on"]:
                assert rank[d] < rank[i]
                assert wave_of[d] < wave_of[i], "dependency in the same or a later wave"
