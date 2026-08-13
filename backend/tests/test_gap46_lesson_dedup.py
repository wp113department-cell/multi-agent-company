"""Stage 2 Day 46 — LessonStore dedup-on-add (answers.md Q120 "Session
Memory": "Compresses repeated information: NO — LessonStore.add() is pure
append, no dedup check against existing lessons"). Mirrors
VersionedLesson.publish()'s dedup pattern (Day 42 did the equivalent for
MemoryEmbedding); LessonStore has no embeddings, so this reuses its own
existing Jaccard token-overlap metric instead.
"""

from __future__ import annotations

import pytest

from app.agents.base_graph import Lesson, LessonStore, get_lesson_store
from app.config import reset_settings_cache


def test_jaccard_direct_known_cases() -> None:
    assert LessonStore._jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert LessonStore._jaccard({"a", "b"}, {"c", "d"}) == 0.0
    # {a,b,c} vs {a,b,d} -> intersection {a,b}=2, union {a,b,c,d}=4 -> 0.5
    assert LessonStore._jaccard({"a", "b", "c"}, {"a", "b", "d"}) == 0.5
    assert LessonStore._jaccard(set(), set()) == 0.0


def test_near_duplicate_lesson_replaces_existing_not_accumulates() -> None:
    store = LessonStore(capacity=100)
    store.add(
        Lesson(
            agent_name="coder",
            lesson="always validate user input at the API boundary",
            pattern="input validation",
            category="best_practice",
        )
    )
    assert store.total == 1

    store.add(
        Lesson(
            agent_name="coder",
            lesson="always validate user input at the api boundary carefully",
            pattern="input validation",
            category="best_practice",
        )
    )
    # Near-duplicate (high token overlap, same category) replaced the
    # original rather than accumulating a second, redundant entry.
    assert store.total == 1
    retrieved = store.retrieve("validate input", top_k=5)
    assert len(retrieved) == 1
    assert "carefully" in retrieved[0].lesson  # the newer phrasing won


def test_distinct_lessons_both_retained() -> None:
    store = LessonStore(capacity=100)
    store.add(
        Lesson(
            agent_name="coder",
            lesson="always validate user input at the API boundary",
            pattern="input validation",
            category="best_practice",
        )
    )
    store.add(
        Lesson(
            agent_name="qa",
            lesson="flaky tests should be quarantined not deleted",
            pattern="test hygiene",
            category="best_practice",
        )
    )
    assert store.total == 2


def test_dedup_scoped_by_category() -> None:
    """Identical text under two different categories must not collapse —
    category is a real semantic distinction, mirrors Day 42's category
    scoping for MemoryEmbedding dedup."""
    store = LessonStore(capacity=100)
    same_text = "retry with exponential backoff on rate limit errors"
    store.add(
        Lesson(
            agent_name="coder",
            lesson=same_text,
            pattern="retry",
            category="best_practice",
        )
    )
    store.add(
        Lesson(
            agent_name="coder",
            lesson=same_text,
            pattern="retry",
            category="failure_mode",
        )
    )
    assert store.total == 2


def test_dedup_disabled_accumulates_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LESSON_DEDUP_ENABLED", "false")
    reset_settings_cache()
    try:
        store = LessonStore(capacity=100)
        lesson = Lesson(
            agent_name="coder",
            lesson="always validate user input at the API boundary",
            pattern="input validation",
            category="best_practice",
        )
        store.add(lesson)
        store.add(lesson)
        assert store.total == 2  # dedup genuinely bypassed
    finally:
        reset_settings_cache()


def test_capacity_still_enforced_with_dedup_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dedup must not disable the pre-existing FIFO eviction guarantee —
    distinct lessons beyond capacity still evict the oldest.

    plan14 Day 2 Task 3 note: this test's synthetic lessons share enough
    template vocabulary ("distinct unrelated lesson number N about topic N")
    to cluster under the new LLM-compression grouping (Jaccard ~0.6+, well
    above lesson_compression_jaccard_threshold's 0.3) — compression is
    disabled here so this test keeps verifying the plain FIFO fallback path
    specifically, without making a real (unmocked) LLM call. Compression
    itself is covered by tests/test_lesson_compression.py."""
    monkeypatch.setenv("LESSON_COMPRESSION_ENABLED", "false")
    reset_settings_cache()
    try:
        store = LessonStore(capacity=3)
        for i in range(5):
            store.add(
                Lesson(
                    agent_name="coder",
                    lesson=f"distinct unrelated lesson number {i} about topic {i}",
                    pattern=f"pattern_{i}",
                    category="best_practice",
                )
            )
        assert store.total == 3
    finally:
        reset_settings_cache()


def test_lesson_store_capacity_is_config_driven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """plan14 Day 2 Task 3 note: compression disabled for the same reason as
    test_capacity_still_enforced_with_dedup_enabled above — this test
    verifies capacity is config-driven via plain FIFO eviction, not
    compression's own grouping behavior."""
    import app.agents.base_graph as base_graph_module

    monkeypatch.setenv("LESSON_STORE_CAPACITY", "2")
    monkeypatch.setenv("LESSON_COMPRESSION_ENABLED", "false")
    reset_settings_cache()
    original_store = base_graph_module._lesson_store
    base_graph_module._lesson_store = None
    try:
        store = get_lesson_store()
        for i in range(5):
            store.add(
                Lesson(
                    agent_name="coder",
                    lesson=f"distinct unrelated lesson number {i} about topic {i}",
                    pattern=f"pattern_{i}",
                    category="best_practice",
                )
            )
        assert store.total == 2
    finally:
        base_graph_module._lesson_store = original_store
        reset_settings_cache()
