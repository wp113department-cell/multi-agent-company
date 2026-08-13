"""plan14 follow-on #7 — General Context Compression.

Before this, `_cap_memory_context_tokens` (app/agents/base_graph.py) handled
an over-budget memory_context with a single hard `memory_context[:max_chars]`
slice — could cut anywhere, including through a high-priority section, just
because a lower-priority one happened to push the combined block over
budget. This replaces it with priority-preserving compression: sections are
kept in their existing priority order (already established by
format_full_memory_context/memory_hook_node — tasks -> failures ->
learnings -> procedures -> preferences -> bugs, with LessonStore's block
ahead of all of them), the first section that doesn't fully fit is
extractively compressed (drops its lowest-similarity-ranked entries, keeps
the heading and the highest-ranked ones), and only sections after that are
dropped entirely.

Deliberately no LLM call anywhere in this path — memory_hook_node runs on
every agent turn's entry, unlike Day 2 Task 3's lesson compression (rare
capacity-eviction events only), so this must stay zero-latency/zero-cost.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.base_graph import (
    _cap_memory_context_tokens,
    _compress_memory_context_to_budget,
    _compress_section_to_budget,
    _split_memory_context_sections,
)
from app.memory.store import format_full_memory_context


def _task(task_id: str, similarity: float, size: int = 300) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "epic_id": None,
        "outcome": "completed",
        "description": "d" * size,
        "summary": "s" * size,
        "files_changed": [],
        "similarity": similarity,
    }


def _failure(task_id: str, similarity: float, size: int = 300) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "error": "e" * size,
        "root_cause": "r" * size,
        "similarity": similarity,
    }


# ---------------------------------------------------------------------------
# _split_memory_context_sections
# ---------------------------------------------------------------------------


def test_split_recovers_all_sections_in_order() -> None:
    ctx = format_full_memory_context(
        tasks=[_task("t1", 0.9)],
        failures=[_failure("f1", 0.8)],
        learnings=[],
    )
    sections = _split_memory_context_sections(ctx)
    assert len(sections) == 2
    assert sections[0].startswith("## Similar past tasks")
    assert sections[1].startswith("## Similar past failures")


def test_split_single_section_returns_one_element() -> None:
    ctx = format_full_memory_context(
        tasks=[_task("t1", 0.9)], failures=[], learnings=[]
    )
    sections = _split_memory_context_sections(ctx)
    assert len(sections) == 1


# ---------------------------------------------------------------------------
# _compress_section_to_budget
# ---------------------------------------------------------------------------


def test_compress_section_keeps_highest_ranked_entries_first() -> None:
    ctx = format_full_memory_context(
        tasks=[_task("high-sim", 0.99, size=200), _task("low-sim", 0.1, size=200)],
        failures=[],
        learnings=[],
    )
    section = _split_memory_context_sections(ctx)[0]
    # Budget room for the heading + first entry only, not the second —
    # computed precisely from the section's own real structure rather than
    # guessed, so the test doesn't depend on exact formatting sizes.
    heading, _, body = section.partition("\n")
    first_entry = body.split("\n\n")[0]
    # +100 margin: enough room for entry 1 AND the "N entries omitted"
    # notice itself (which the notice-fits check also bounds — see
    # test_cap_over_budget_never_exceeds_bound for the boundary case where
    # the notice doesn't fit and is correctly omitted instead).
    remaining_chars = len(heading) + 2 + len(first_entry) + 100
    compressed = _compress_section_to_budget(section, remaining_chars)
    assert compressed is not None
    assert "high-sim" in compressed
    assert "low-sim" not in compressed
    assert "omitted to fit token budget" in compressed
    assert len(compressed) <= remaining_chars


def test_compress_section_returns_none_when_heading_itself_does_not_fit() -> None:
    section = "## A fairly long heading that will not fit\nbody"
    assert _compress_section_to_budget(section, remaining_chars=5) is None


def test_compress_section_keeps_all_entries_when_everything_fits() -> None:
    ctx = format_full_memory_context(
        tasks=[_task("t1", 0.9, size=50)], failures=[], learnings=[]
    )
    section = _split_memory_context_sections(ctx)[0]
    compressed = _compress_section_to_budget(
        section, remaining_chars=len(section) + 100
    )
    assert compressed == section
    assert "omitted" not in compressed


# ---------------------------------------------------------------------------
# _compress_memory_context_to_budget — priority-preserving, whole-context
# ---------------------------------------------------------------------------


def test_high_priority_section_survives_intact_when_low_priority_pushes_over_budget() -> (
    None
):
    """The real property this whole feature exists for: a small,
    high-priority section (tasks) must come through completely unmodified
    even when a much larger low-priority section (failures) is what
    actually causes the overflow — the OLD hard-slice-from-the-front
    behavior could never guarantee this (a big enough first section would
    itself get cut)."""
    small_task_section = format_full_memory_context(
        tasks=[_task("critical", 0.99, size=30)], failures=[], learnings=[]
    )
    tasks_section = _split_memory_context_sections(small_task_section)[0]

    big_failures_ctx = format_full_memory_context(
        tasks=[],
        failures=[_failure(f"f{i}", 0.5, size=300) for i in range(20)],
        learnings=[],
    )
    failures_section = _split_memory_context_sections(big_failures_ctx)[0]

    combined = tasks_section + "\n\n" + failures_section
    budget_chars = len(tasks_section) + 200  # room for tasks + a bit of failures

    compressed, changed = _compress_memory_context_to_budget(combined, budget_chars)
    assert changed is True
    assert tasks_section in compressed
    assert "critical" in compressed
    assert len(compressed) <= budget_chars


def test_sections_beyond_budget_are_dropped_entirely() -> None:
    ctx1 = format_full_memory_context(
        tasks=[_task("t1", 0.9, size=20)], failures=[], learnings=[]
    )
    s1 = _split_memory_context_sections(ctx1)[0]
    ctx2 = format_full_memory_context(
        tasks=[], failures=[_failure("f1", 0.9, size=20)], learnings=[]
    )
    s2 = _split_memory_context_sections(ctx2)[0]

    combined = s1 + "\n\n" + s2
    # Budget so tight only the first section's heading fits.
    compressed, changed = _compress_memory_context_to_budget(combined, len(s1))
    assert changed is True
    assert "Similar past failures" not in compressed


def test_nothing_dropped_when_everything_fits() -> None:
    ctx = format_full_memory_context(
        tasks=[_task("t1", 0.9, size=20)], failures=[], learnings=[]
    )
    compressed, changed = _compress_memory_context_to_budget(ctx, len(ctx) + 1000)
    assert changed is False
    assert compressed == ctx


# ---------------------------------------------------------------------------
# _cap_memory_context_tokens — public entry point
# ---------------------------------------------------------------------------


def test_cap_under_budget_passes_through_unchanged() -> None:
    small = "short text"
    assert _cap_memory_context_tokens(small, trace_id="t") == small


def test_cap_over_budget_never_exceeds_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "memory_injection_token_budget", 50)
    ctx = format_full_memory_context(
        tasks=[_task(f"t{i}", 0.9 - i * 0.01, size=400) for i in range(10)],
        failures=[_failure(f"f{i}", 0.8, size=400) for i in range(10)],
        learnings=[],
    )
    result = _cap_memory_context_tokens(ctx, trace_id="t")
    marker = (
        "\n\n[...memory context compressed to fit token budget — "
        "lowest-priority section(s)/entries trimmed first...]"
    )
    assert len(result) <= 50 * 4 + len(marker)
    assert "compressed to fit token budget" in result


def test_cap_over_budget_preserves_highest_priority_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end proof through the public entry point: the most relevant
    (highest-similarity) task survives even though the whole context is
    forced far below its natural size."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "memory_injection_token_budget", 60)
    ctx = format_full_memory_context(
        tasks=[_task("most-relevant-task", 0.99, size=10)],
        failures=[_failure(f"f{i}", 0.5, size=400) for i in range(15)],
        learnings=[],
    )
    result = _cap_memory_context_tokens(ctx, trace_id="t")
    assert "most-relevant-task" in result


def test_disabled_when_budget_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "memory_injection_token_budget", 0)
    huge = "a" * 100_000
    assert _cap_memory_context_tokens(huge, trace_id="t") == huge
