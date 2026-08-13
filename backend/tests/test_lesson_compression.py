"""plan14 Day 2 Task 3 — Session Memory Compression.

The governing 5-day spec's own instruction: "LessonStore already exists and
has retention, deduplication, replacement, bounded capacity — do NOT create
another session-memory system, extend it." This extends LessonStore.add()'s
at-capacity path: instead of always blindly evicting the oldest lesson
(FIFO), it first tries to find the largest group of related (same-category,
Jaccard-overlapping) lessons and LLM-compress them into one, falling back to
the pre-existing FIFO eviction when compression is disabled, no group
qualifies, or the LLM call fails.

Every test that could reach the LLM call path mocks anthropic.Anthropic —
this suite's own established convention (see conftest.py: "Unit tests never
make real LLM calls"). Two pre-existing tests in test_gap46_lesson_dedup.py
and test_base_graph_scaffold.py were updated alongside this file to disable
compression explicitly, since their synthetic lesson text happens to cluster
under the new grouping and they predate this feature (they test plain FIFO
eviction specifically).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.base_graph import Lesson, LessonStore, _group_compressible_lessons
from app.config import get_settings, reset_settings_cache


def _mock_anthropic_response(text: str) -> Any:
    return MagicMock(
        content=[MagicMock(type="text", text=text)],
        usage=MagicMock(input_tokens=10, output_tokens=5),
    )


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    settings = get_settings()
    assert settings.lesson_compression_enabled is True
    assert settings.lesson_compression_min_group_size == 3
    assert settings.lesson_compression_jaccard_threshold == 0.3
    assert settings.lesson_compression_llm_timeout_seconds == 10.0


# ---------------------------------------------------------------------------
# _group_compressible_lessons — pure grouping logic, no I/O
# ---------------------------------------------------------------------------


def test_group_finds_largest_qualifying_cluster() -> None:
    lessons = [
        Lesson("a", "retry api calls with exponential backoff", "retry", "reliability"),
        Lesson(
            "b",
            "retry network calls with exponential backoff too",
            "retry",
            "reliability",
        ),
        Lesson(
            "c",
            "retry with exponential backoff on every api call",
            "retry",
            "reliability",
        ),
        Lesson(
            "d", "completely unrelated fact about docker networking", "docker", "infra"
        ),
    ]
    group = _group_compressible_lessons(
        lessons, min_group_size=3, jaccard_threshold=0.3
    )
    assert group is not None
    assert len(group) == 3
    assert all(ls.category == "reliability" for ls in group)


def test_group_respects_category_boundary() -> None:
    lessons = [
        Lesson("a", "always validate input", "validate", "security"),
        Lesson("b", "always validate input", "validate", "best_practice"),
        Lesson("c", "always validate input", "validate", "testing"),
    ]
    # Identical text, but 3 different categories — no single category has
    # min_group_size=3 lessons, so no group qualifies.
    group = _group_compressible_lessons(
        lessons, min_group_size=3, jaccard_threshold=0.3
    )
    assert group is None


def test_group_returns_none_below_min_size() -> None:
    lessons = [
        Lesson("a", "retry with backoff", "retry", "reliability"),
        Lesson("b", "retry with backoff too", "retry", "reliability"),
    ]
    group = _group_compressible_lessons(
        lessons, min_group_size=3, jaccard_threshold=0.3
    )
    assert group is None


def test_group_returns_none_when_all_distinct() -> None:
    lessons = [
        Lesson("a", "docker networking uses bridge mode by default", "docker", "infra"),
        Lesson("b", "postgres connection pooling needs a real limit", "pg", "database"),
        Lesson(
            "c", "flaky tests should be quarantined not deleted", "flaky", "testing"
        ),
    ]
    group = _group_compressible_lessons(
        lessons, min_group_size=3, jaccard_threshold=0.3
    )
    assert group is None


# ---------------------------------------------------------------------------
# LessonStore._compress_group — LLM call, mocked
# ---------------------------------------------------------------------------


def test_compress_group_builds_merged_lesson_from_llm_response() -> None:
    store = LessonStore(capacity=100)
    group = [
        Lesson("a", "retry api calls with backoff", "retry", "reliability"),
        Lesson("b", "retry network calls with backoff", "retry", "reliability"),
        Lesson("c", "retry with backoff on every call", "retry", "reliability"),
    ]
    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_anthropic_response(
            "Always retry API and network calls with exponential backoff."
        )
        compacted = store._compress_group(group)

    assert compacted is not None
    assert (
        compacted.lesson
        == "Always retry API and network calls with exponential backoff."
    )
    assert compacted.category == "reliability"
    assert compacted.pattern == "retry"
    assert compacted.agent_name == "lesson_compression"
    assert compacted.reusable is True


def test_compress_group_returns_none_on_empty_llm_response() -> None:
    store = LessonStore(capacity=100)
    group = [
        Lesson("a", "x", "p", "cat"),
        Lesson("b", "y", "p", "cat"),
        Lesson("c", "z", "p", "cat"),
    ]
    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_anthropic_response(
            ""
        )
        compacted = store._compress_group(group)
    assert compacted is None


def test_compress_group_returns_none_on_llm_failure() -> None:
    store = LessonStore(capacity=100)
    group = [
        Lesson("a", "x", "p", "cat"),
        Lesson("b", "y", "p", "cat"),
        Lesson("c", "z", "p", "cat"),
    ]
    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.side_effect = RuntimeError("api down")
        compacted = store._compress_group(group)
    assert compacted is None


def test_compress_group_uses_isolated_short_timeout_zero_retry_client() -> None:
    """Must NOT go through _make_client()/_call_anthropic()'s shared,
    breaker-wrapped, 300s-timeout path — a background compaction failure
    must never count toward the circuit breaker real critical-path agent
    submissions depend on, and must never block LessonStore.add()'s hot
    path anywhere near 300s."""
    store = LessonStore(capacity=100)
    group = [
        Lesson("a", "x", "p", "cat"),
        Lesson("b", "y", "p", "cat"),
        Lesson("c", "z", "p", "cat"),
    ]
    with (
        patch("anthropic.Anthropic") as mock_cls,
        patch("app.fleet.circuit_breaker.get_anthropic_breaker") as mock_breaker,
    ):
        mock_cls.return_value.messages.create.return_value = _mock_anthropic_response(
            "merged"
        )
        store._compress_group(group)

    mock_breaker.assert_not_called()
    _, kwargs = mock_cls.call_args
    assert kwargs["timeout"] == 10.0
    assert kwargs["max_retries"] == 0


# ---------------------------------------------------------------------------
# LessonStore.add() end to end at capacity
# ---------------------------------------------------------------------------


def test_add_compresses_related_group_at_capacity_instead_of_fifo() -> None:
    store = LessonStore(capacity=3)
    for i in range(3):
        store.add(
            Lesson(
                "coder",
                f"retry api calls with backoff variant {i}",
                "retry",
                "reliability",
            )
        )
    assert store.total == 3

    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_anthropic_response(
            "Always retry API calls with backoff."
        )
        store.add(Lesson("qa", "completely unrelated docker fact", "docker", "infra"))

    # 3 related lessons compacted into 1 + the new unrelated lesson = 2,
    # not 3 (which plain FIFO eviction would have produced).
    assert store.total == 2
    categories = {ls.category for ls in store._lessons}
    assert categories == {"reliability", "infra"}
    compacted = next(ls for ls in store._lessons if ls.category == "reliability")
    assert compacted.agent_name == "lesson_compression"


def test_add_falls_back_to_fifo_when_compression_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LESSON_COMPRESSION_ENABLED", "false")
    reset_settings_cache()
    try:
        store = LessonStore(capacity=3)
        for i in range(3):
            store.add(
                Lesson(
                    "coder",
                    f"retry api calls with backoff variant {i}",
                    "retry",
                    "reliability",
                )
            )
        with patch("anthropic.Anthropic") as mock_cls:
            store.add(
                Lesson("qa", "completely unrelated docker fact", "docker", "infra")
            )
        mock_cls.assert_not_called()
        assert store.total == 3  # plain FIFO: oldest evicted, still 3 total
    finally:
        reset_settings_cache()


def test_add_falls_back_to_fifo_when_no_group_qualifies() -> None:
    store = LessonStore(capacity=3)
    store.add(Lesson("a", "docker networking uses bridge mode", "docker", "infra"))
    store.add(Lesson("b", "postgres pooling needs a real limit", "pg", "database"))
    store.add(Lesson("c", "flaky tests should be quarantined", "flaky", "testing"))

    with patch("anthropic.Anthropic") as mock_cls:
        store.add(Lesson("d", "a fourth, also unrelated fact", "misc", "other"))

    mock_cls.assert_not_called()
    assert store.total == 3  # FIFO fallback, unchanged behavior


def test_add_falls_back_to_fifo_when_llm_call_fails() -> None:
    store = LessonStore(capacity=3)
    for i in range(3):
        store.add(
            Lesson(
                "coder",
                f"retry api calls with backoff variant {i}",
                "retry",
                "reliability",
            )
        )

    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value.messages.create.side_effect = RuntimeError("api down")
        store.add(Lesson("qa", "completely unrelated docker fact", "docker", "infra"))

    # Compression attempted and failed -> plain FIFO fallback -> still 3,
    # not crashed, not silently dropping the new lesson.
    assert store.total == 3
    assert any(ls.category == "infra" for ls in store._lessons)
