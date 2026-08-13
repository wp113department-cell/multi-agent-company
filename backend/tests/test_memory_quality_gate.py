"""plan14 Day 2 Task 4 — Memory Quality Gate.

A deterministic (no LLM, no regex) pre-store gate for memory_embeddings
writes: near-empty/placeholder candidates are rejected outright (never
inserted); borderline-specificity candidates are still inserted but as a
draft (verified=False, dampened importance — de-prioritized in the existing
composite ranking, not hidden from retrieval); everything else publishes
exactly as before this change.

Scope note: this covers memory_embeddings writes only — the "routine memory"
tier. The separate lessons/versioned_lessons system is untouched (see Day 2
Task 3's tests/test_lesson_compression.py and Day 3 Task 5's consolidation
work instead).

Design note proven by a real regression during this task: draft rows use
verified=False + dampened importance, NOT the `archived` column —
archived/archived_at are app/services/retention.py's own hard exclusion
filter, and pre-setting archived=True at write time made the retention job
find zero candidates for that row forever
(tests/test_memory_archived_filter.py caught this live). verified/importance
are confirmed soft, ranking-only signals.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings, reset_settings_cache
from app.db.models import MemoryEmbedding
from app.memory.store import (
    MemoryQualityDecision,
    embed_bug,
    embed_preference,
    embed_task_outcome,
    evaluate_memory_quality,
)


def _vector_for(text_to_embed: str) -> list[float]:
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    settings = get_settings()
    assert settings.memory_quality_gate_enabled is True
    assert settings.memory_quality_reject_min_length_chars == 15
    assert settings.memory_quality_draft_min_length_chars == 40
    assert settings.memory_quality_draft_min_distinct_tokens == 6
    assert settings.memory_quality_draft_importance_factor == 0.3


# ---------------------------------------------------------------------------
# evaluate_memory_quality — pure function
# ---------------------------------------------------------------------------


def test_empty_content_is_rejected() -> None:
    result = evaluate_memory_quality("", "")
    assert result.action == "reject"


def test_placeholder_content_is_rejected() -> None:
    for junk in ("done", "ok", "n/a", "-"):
        result = evaluate_memory_quality(junk)
        assert result.action == "reject", f"{junk!r} should be rejected"


def test_short_but_real_content_is_not_rejected() -> None:
    """Regression guard: 'desc A'/'summary A'-style short-but-real content
    (used across several pre-existing repo-scoping tests) must never be
    silently dropped — only genuinely near-empty content should reject."""
    result = evaluate_memory_quality("desc A", "summary A")
    assert result.action != "reject"


def test_short_stated_preference_is_at_most_drafted_never_rejected() -> None:
    """A real, legitimately short preference must never be rejected outright
    — the master spec's own explicit example."""
    result = evaluate_memory_quality("use tabs not spaces")
    assert result.action in ("draft", "publish")


def test_borderline_content_is_drafted() -> None:
    result = evaluate_memory_quality("a short note about something")
    assert result.action == "draft"


def test_substantial_content_is_published() -> None:
    result = evaluate_memory_quality(
        "The root cause was a race condition in the connection pool where "
        "two threads acquired the same connection object simultaneously",
        "Fixed by adding a per-connection lock around the acquire/release path",
    )
    assert result.action == "publish"


def test_gate_disabled_always_publishes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_QUALITY_GATE_ENABLED", "false")
    reset_settings_cache()
    try:
        assert evaluate_memory_quality("").action == "publish"
        assert evaluate_memory_quality("x").action == "publish"
    finally:
        reset_settings_cache()


def test_decision_reports_length_and_token_counts() -> None:
    result = evaluate_memory_quality("hello world")
    assert isinstance(result, MemoryQualityDecision)
    assert result.length == len("hello world")
    assert result.distinct_tokens == 2


# ---------------------------------------------------------------------------
# Real-DB integration — embed_* functions actually apply the gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_task_outcome_rejects_near_empty_content(
    _mock_embed: object,
) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-qgate-reject-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_task_outcome(
                task_id=task_id,
                description="",
                summary="ok",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert row is None

            from sqlalchemy import select

            result = await session.execute(
                select(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            assert result.scalar_one_or_none() is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_task_outcome_drafts_borderline_content(
    _mock_embed: object,
) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-qgate-draft-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_task_outcome(
                task_id=task_id,
                description="a short note",
                summary="brief",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert row is not None
            assert row.verified is False
            # completed outcome normally gets _default_importance("task", "completed")
            # == 0.5; draft tier dampens it by memory_quality_draft_importance_factor.
            assert row.importance < 0.5

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_task_outcome_publishes_substantial_content_unchanged(
    _mock_embed: object,
) -> None:
    """Regression guard: real, substantial content keeps today's exact
    importance/verified behavior — the gate must be a no-op for normal
    production-shaped writes."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-qgate-publish-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_task_outcome(
                task_id=task_id,
                description=(
                    "Implemented the retry-with-backoff wrapper around the "
                    "flaky external API client and added jitter to avoid a "
                    "thundering herd on reconnect"
                ),
                summary="Added retry wrapper with exponential backoff and jitter",
                outcome="completed",
                files_changed=["app/clients/external.py"],
                db=session,
            )
            assert row is not None
            assert row.verified is True  # outcome == "completed", unchanged
            assert row.importance == pytest.approx(0.5)  # unchanged, no dampening

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_task_outcome_draft_row_still_appears_in_query_results(
    _mock_embed: object,
) -> None:
    """Draft must not hide a row from retrieval — only from full-weight
    ranking. This is the real behavioral difference from the (rejected)
    archived-based design."""
    from app.memory.store import query_similar_tasks

    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-qgate-visible-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_task_outcome(
                task_id=task_id,
                description="a short note",
                summary="brief",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert row is not None
            assert row.verified is False  # confirmed draft-tier

            results = await query_similar_tasks(
                "irrelevant query text", session, top_k=1000
            )
            task_ids = {r["task_id"] for r in results}
            assert task_id in task_ids

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_preference_short_real_preference_not_rejected(
    _mock_embed: object,
) -> None:
    """The master spec's own explicit example must survive end to end, not
    just at the pure-function level."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-qgate-pref-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_preference(
                task_id=task_id,
                preference="use tabs not spaces",
                scope="style",
                db=session,
            )
            assert row is not None

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_bug_rejects_empty_issue(_mock_embed: object) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-qgate-bug-reject-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_bug(task_id=task_id, issue="", severity="low", db=session)
            assert row is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_embed_task_outcome_gate_disabled_publishes_even_near_empty(
    _mock_embed: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEMORY_QUALITY_GATE_ENABLED", "false")
    reset_settings_cache()
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-qgate-disabled-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = await embed_task_outcome(
                task_id=task_id,
                description="",
                summary="ok",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            assert row is not None
            assert row.verified is True  # gate disabled -> today's exact behavior

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await session.commit()
    finally:
        reset_settings_cache()
        await engine.dispose()
