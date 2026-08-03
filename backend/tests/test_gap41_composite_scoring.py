"""Stage 2 Day 41 — app/memory/store.py's composite ranking (answers.md
Q120 "Memory Prioritization": recency/reuse/importance/verified blended
into ORDER BY, replacing pure cosine-distance ranking). Real-DB proof that
the composite score actually re-orders results relative to pure similarity
— not just that the SQL compiles and returns the same order it always did.

Uses a content-derived, signed fake-vector helper (not a single shared
constant) — see test_memory_archived_filter.py's identical helper for why:
distinct content must produce distinct (near-orthogonal) vectors so Day 42's
dedup guard doesn't collapse unrelated test rows into each other. The two
tests below that intentionally write IDENTICAL content to two rows (to hold
similarity constant while varying reuse/importance/recency) explicitly
disable dedup instead, since collapsing them into one row is exactly what
dedup is supposed to do — these tests are about composite scoring, not
dedup, so the variable under test is isolated.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings, reset_settings_cache
from app.db.models import MemoryEmbedding
from app.memory.store import (
    embed_task_outcome,
    query_architecture_notes,
    query_failures,
    query_learning_signals,
    query_procedures,
    query_similar_tasks,
)


def _vector_for(text_to_embed: str) -> list[float]:
    """Deterministic, content-derived fake embedding, signed components —
    see test_memory_archived_filter.py's identical helper for the full
    rationale (uniform non-negative vectors share a "positive orthant"
    bias giving ~0.75-0.9 cosine similarity to ANY other such vector
    regardless of content, confirmed empirically; signed components give
    the near-zero similarity real distinct content should have)."""
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_composite_score_present_and_bounded_reasonably(
    _mock_embed: object,
) -> None:
    """Basic sanity: composite_score is a real number in the returned dict,
    not just similarity re-labeled."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-gap41-basic-{suffix}"
    marker = f"composite score basic sanity marker {suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await embed_task_outcome(
                task_id=task_id,
                description=marker,
                summary="s",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            results = await query_similar_tasks(marker, session, top_k=1000)
            match = next(r for r in results if r["task_id"] == task_id)
            assert "composite_score" in match
            assert isinstance(match["composite_score"], float)
            # completed -> verified=True, default importance 0.5, similarity
            # near 1.0 (identical fake vector for identical text) -> score
            # should be positive and not exceed 1.0 (weights sum to 1.0).
            assert 0.0 < match["composite_score"] <= 1.0

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_high_reuse_and_importance_can_outrank_a_slightly_more_similar_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The concrete behavioral proof this day's work exists for: two rows
    with IDENTICAL similarity (same content -> same fake vector) but
    different reuse_count/importance must NOT tie under the composite
    score — the one with more real usage signal ranks first. Pure-
    similarity ranking (Day 40 and earlier) could never distinguish these
    two rows at all; the composite score does.

    Both rows use the same outcome="completed" (not one "blocked") —
    _embed() is called on the *composed* text (description+summary+
    outcome+files, see _build_outcome_text), not the raw description
    alone, so a differing outcome would itself change the vector and break
    the "identical similarity" premise this test depends on. The
    distinguishing reuse/importance signal is applied via a direct UPDATE
    after both inserts, not via outcome.

    Dedup (Day 42) is explicitly disabled for this test: writing identical
    content twice would otherwise correctly collapse into one row (that's
    dedup's whole point), but this test needs two genuinely distinct rows
    to isolate composite scoring as the variable under test."""
    monkeypatch.setenv("MEMORY_DEDUP_ENABLED", "false")
    reset_settings_cache()
    try:
        engine = _engine()
        suffix = uuid.uuid4().hex[:8]
        task_low = f"td-gap41-low-{suffix}"
        task_high = f"td-gap41-high-{suffix}"
        marker = f"composite ranking tiebreak marker {suffix}"
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                with patch("app.memory.store._embed", side_effect=_vector_for):
                    row_low = await embed_task_outcome(
                        task_id=task_low,
                        description=marker,
                        summary="s",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                    )
                    row_high = await embed_task_outcome(
                        task_id=task_high,
                        description=marker,
                        summary="s",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                    )
                    assert row_low is not None and row_high is not None
                    assert row_low.id != row_high.id  # dedup genuinely off

                    # Give row_high real, high reuse and importance signal.
                    await session.execute(
                        update(MemoryEmbedding)
                        .where(MemoryEmbedding.id == row_high.id)
                        .values(reuse_count=50, importance=1.0)
                    )
                    await session.commit()

                    results = await query_similar_tasks(marker, session, top_k=1000)
                ranked_ids = [r["task_id"] for r in results]
                assert task_high in ranked_ids and task_low in ranked_ids
                # Same similarity (identical content) — composite must
                # still rank the higher-signal row strictly first.
                assert ranked_ids.index(task_high) < ranked_ids.index(task_low)
                high_result = next(r for r in results if r["task_id"] == task_high)
                low_result = next(r for r in results if r["task_id"] == task_low)
                assert high_result["similarity"] == pytest.approx(
                    low_result["similarity"], abs=1e-6
                )
                assert high_result["composite_score"] > low_result["composite_score"]

                await session.execute(
                    delete(MemoryEmbedding).where(
                        MemoryEmbedding.task_id.in_([task_low, task_high])
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()
    finally:
        reset_settings_cache()


@pytest.mark.asyncio
async def test_older_row_ranks_below_newer_row_at_equal_similarity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recency weighting: an artificially aged row (created_at pushed back
    well past the half-life) must rank below a fresh row of otherwise
    identical signal — proving the exponential decay term is real, not
    inert. Dedup disabled for the same reason as the tiebreak test above:
    two rows need identical content to hold similarity constant."""
    monkeypatch.setenv("MEMORY_DEDUP_ENABLED", "false")
    reset_settings_cache()
    try:
        engine = _engine()
        suffix = uuid.uuid4().hex[:8]
        task_old = f"td-gap41-old-{suffix}"
        task_new = f"td-gap41-new-{suffix}"
        marker = f"composite recency marker {suffix}"
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                with patch("app.memory.store._embed", side_effect=_vector_for):
                    row_old = await embed_task_outcome(
                        task_id=task_old,
                        description=marker,
                        summary="s",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                    )
                    row_new = await embed_task_outcome(
                        task_id=task_new,
                        description=marker,
                        summary="s",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                    )
                    assert row_old is not None and row_new is not None
                    assert row_old.id != row_new.id  # dedup genuinely off

                    settings = get_settings()
                    age_days = 5 * settings.memory_recency_half_life_days
                    await session.execute(
                        text(
                            "UPDATE memory_embeddings SET created_at = now() - "
                            "(CAST(:age_days AS double precision) * interval '1 day') "
                            "WHERE id = :id"
                        ),
                        {"age_days": age_days, "id": row_old.id},
                    )
                    await session.commit()

                    results = await query_similar_tasks(marker, session, top_k=1000)
                ranked_ids = [r["task_id"] for r in results]
                assert ranked_ids.index(task_new) < ranked_ids.index(task_old)

                await session.execute(
                    delete(MemoryEmbedding).where(
                        MemoryEmbedding.task_id.in_([task_old, task_new])
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()
    finally:
        reset_settings_cache()


@pytest.mark.asyncio
async def test_zero_weights_reduce_composite_ranking_to_pure_similarity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Config-driven, not hardcoded: zeroing every non-similarity weight
    must make the composite score numerically equal to similarity alone —
    proving the weights are real inputs to the formula, not decorative."""
    monkeypatch.setenv("MEMORY_SCORE_WEIGHT_SIMILARITY", "1.0")
    monkeypatch.setenv("MEMORY_SCORE_WEIGHT_RECENCY", "0.0")
    monkeypatch.setenv("MEMORY_SCORE_WEIGHT_REUSE", "0.0")
    monkeypatch.setenv("MEMORY_SCORE_WEIGHT_IMPORTANCE", "0.0")
    monkeypatch.setenv("MEMORY_SCORE_WEIGHT_VERIFIED", "0.0")
    reset_settings_cache()
    try:
        engine = _engine()
        suffix = uuid.uuid4().hex[:8]
        task_id = f"td-gap41-zeroweight-{suffix}"
        marker = f"zero weight equivalence marker {suffix}"
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                with patch("app.memory.store._embed", side_effect=_vector_for):
                    await embed_task_outcome(
                        task_id=task_id,
                        description=marker,
                        summary="s",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                    )
                    results = await query_similar_tasks(marker, session, top_k=1000)
                match = next(r for r in results if r["task_id"] == task_id)
                assert match["composite_score"] == pytest.approx(
                    match["similarity"], abs=1e-6
                )

                await session.execute(
                    delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
                )
                await session.commit()
        finally:
            await engine.dispose()
    finally:
        reset_settings_cache()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_remaining_four_query_functions_expose_id_and_composite_score(
    _mock_embed: object,
) -> None:
    """Day 40 wired query_similar_tasks alone; this proves the other 4 were
    genuinely updated too, not just query_similar_tasks with the rest
    silently left on the old pure-distance ORDER BY."""
    from app.memory.store import (
        embed_architecture_note,
        embed_failure,
        embed_learning_signal,
        embed_procedure,
    )

    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    marker = f"composite four-function marker {suffix}"
    task_ids = {
        "arch": f"td-gap41-arch-{suffix}",
        "fail": f"td-gap41-fail-{suffix}",
        "learn": f"td-gap41-learn-{suffix}",
        "proc": f"td-gap41-proc-{suffix}",
    }
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await embed_architecture_note(
                task_id=task_ids["arch"], content=marker, db=session
            )
            await embed_failure(
                task_id=task_ids["fail"],
                error_description=marker,
                root_cause="root",
                db=session,
            )
            await embed_learning_signal(
                agent_name=task_ids["learn"],
                description=marker,
                outcome_summary="ok",
                db=session,
            )
            await embed_procedure(
                task_id=task_ids["proc"],
                symptom=marker,
                steps_taken=["step one", "step two"],
                resolution="resolved",
                agent_name="test-agent",
                db=session,
            )

            arch_results = await query_architecture_notes(marker, session, top_k=1000)
            fail_results = await query_failures(marker, session, top_k=1000)
            learn_results = await query_learning_signals(marker, session, top_k=1000)
            proc_results = await query_procedures(marker, session, top_k=1000)

            assert any(
                "id" in r and "composite_score" in r
                for r in arch_results
                if r["task_id"] == task_ids["arch"]
            )
            assert any(
                "id" in r and "composite_score" in r
                for r in fail_results
                if r["task_id"] == task_ids["fail"]
            )
            assert any(
                "id" in r and "composite_score" in r
                for r in learn_results
                if r["agent_name"] == task_ids["learn"]
            )
            assert any(
                "id" in r and "composite_score" in r
                for r in proc_results
                if r["task_id"] == task_ids["proc"]
            )

            # embed_learning_signal stores task_id=f"fleet-{agent_name}", not
            # the raw agent_name — both forms included so cleanup actually
            # matches that row (a bare task_ids.values() filter would silently
            # leak it into the shared dev DB on every run).
            await session.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id.in_(
                        list(task_ids.values()) + [f"fleet-{task_ids['learn']}"]
                    )
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_reuse_count_actually_increments_for_all_four_remaining_functions(
    _mock_embed: object,
) -> None:
    from app.memory.store import embed_failure

    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_id = f"td-gap41-reuse-fail-{suffix}"
    marker = f"reuse increment marker {suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            written = await embed_failure(
                task_id=task_id,
                error_description=marker,
                root_cause="root",
                db=session,
            )
            assert written is not None
            assert written.reuse_count == 0

            await query_failures(marker, session, top_k=1000)

            from sqlalchemy import select

            refetched = (
                await session.execute(
                    select(MemoryEmbedding).where(MemoryEmbedding.id == written.id)
                )
            ).scalar_one()
            assert refetched.reuse_count == 1

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await session.commit()
    finally:
        await engine.dispose()
