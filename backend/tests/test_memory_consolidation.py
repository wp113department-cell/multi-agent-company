"""plan14 Day 3 Task 5 — Memory Consolidation.

Extends versioned_memory.py's existing pairwise merge-at-draft-time
mechanism (Day 11) to N-way, via two additions:

1. Reactive: promote() now also sweeps for and merges (state='merged_into')
   any OTHER currently-published lesson within memory_merge_similarity_
   threshold of the just-promoted lesson's embedding — catching lessons
   that drifted into overlapping topics without ever being compared against
   each other at their own individual draft time (publish()'s own
   _find_most_similar_published only ever looks at state='published' rows,
   so two lessons drafted before either is promoted never see each other).

2. Proactive: consolidate_published_lessons() scans existing published
   lessons, clusters them by real cosine similarity, and proposes a merged
   DRAFT per qualifying cluster — never auto-published; promoting that
   draft (via the existing memory_promote_lesson tool, exactly like any
   other draft) then triggers #1 above, which transparently merges away the
   original cluster members.

Real-DB integration tests use the exact "publish both as drafts before
promoting either" timing trick to construct the specific scenario this
feature exists for: two similar lessons that predate() any promotion (so
neither's own draft-time pairwise check ever saw the other).
"""

from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.fleet.versioned_memory import (
    VersionedMemoryStore,
    _cluster_by_similarity,
    _cosine_similarity,
)

# Real-DB integration tests below publish() real rows against fixed topic
# strings. A per-run suffix keeps every test's topics collision-proof against
# any leftover row from a prior interrupted run (real hazard hit while
# developing this file: an old row from a crashed manual debugging session
# kept making a LATER run's own _find_most_similar_published falsely match
# and attempt a real, unmocked LLM merge) — not just relying on every test's
# own cleanup succeeding every single time.
_SFX = uuid.uuid4().hex[:8]

_RNG = random.Random(4242)
_VEC_A = [_RNG.random() for _ in range(1536)]
_VEC_A_SIMILAR = [v + 0.0001 for v in _VEC_A]
_VEC_B = [_RNG.random() for _ in range(1536)]


def _cleanup(*lesson_ids: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import VersionedLesson

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(VersionedLesson).where(
                        VersionedLesson.lesson_id.in_(lesson_ids)
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _cleanup_memory_embeddings(task_id: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import MemoryEmbedding

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


async def _state_of(lesson_id: str) -> list[tuple[int, str]]:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import VersionedLesson

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            rows = (
                (
                    await session.execute(
                        select(VersionedLesson)
                        .where(VersionedLesson.lesson_id == lesson_id)
                        .order_by(VersionedLesson.version.asc())
                    )
                )
                .scalars()
                .all()
            )
            return [(r.version, r.state) for r in rows]
    finally:
        await engine.dispose()


def _mock_merge_response(text: str) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _patched_embed(vectors: list[list[float]]) -> Any:
    queue = iter(vectors)

    async def _fake_embed(text: str) -> list[float]:
        return next(queue)

    return _fake_embed


# ---------------------------------------------------------------------------
# Pure functions — no I/O
# ---------------------------------------------------------------------------


def test_cosine_similarity_identical_vectors_is_one() -> None:
    v = [1.0, 2.0, 3.0]
    assert _cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero() -> None:
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors_is_negative_one() -> None:
    assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector_is_zero_not_nan() -> None:
    assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_cluster_by_similarity_finds_related_pair() -> None:
    candidates = [
        (1, "t1", "content A", _VEC_A),
        (2, "t2", "content A similar", _VEC_A_SIMILAR),
        (3, "t3", "content B, unrelated", _VEC_B),
    ]
    clusters = _cluster_by_similarity(candidates, threshold=0.85)
    assert len(clusters) == 1
    assert {c[0] for c in clusters[0]} == {1, 2}


def test_cluster_by_similarity_excludes_singletons() -> None:
    candidates = [
        (1, "t1", "content A", _VEC_A),
        (2, "t2", "content B, unrelated", _VEC_B),
    ]
    clusters = _cluster_by_similarity(candidates, threshold=0.85)
    assert clusters == []


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    from app.config import get_settings

    settings = get_settings()
    assert settings.memory_consolidation_enabled is True
    assert settings.memory_consolidation_max_merge_per_promote == 20
    assert settings.memory_consolidation_max_candidates == 200
    assert settings.memory_consolidation_min_cluster_size == 2
    assert settings.memory_consolidation_interval_hours == 24.0


# ---------------------------------------------------------------------------
# Reactive sweep — real DB, via promote()
# ---------------------------------------------------------------------------


def test_promote_merges_a_published_lesson_that_predates_it_and_is_similar() -> None:
    """The real scenario this feature exists for: A and B are both drafted
    before either is promoted, so publish()'s own draft-time pairwise check
    (_find_most_similar_published, which only ever looks at state=
    'published' rows) never compares them against each other. Promoting A
    first finds nothing (B isn't published yet). Promoting B second — now
    that A IS published — is what triggers the reactive sweep to merge A."""
    lesson_a_id: str | None = None
    lesson_b_id: str | None = None
    try:
        with patch(
            "app.memory.store._embed",
            # publish() calls _embed exactly once per call (only a SECOND
            # time if it merges — neither does here, since A isn't
            # published when B is drafted). promote() ALSO calls _embed
            # once, via _sync_to_memory_embeddings -> embed_learning_signal
            # — easy to miss, and the actual root cause the first version
            # of this test got wrong. Order: A's content, B's content
            # (similar to A — the point of this test), A-promote's sync
            # (value irrelevant), B-promote's sync (value irrelevant).
            _patched_embed([_VEC_A, _VEC_A_SIMILAR, _VEC_B, _VEC_B]),
        ):
            store = VersionedMemoryStore()
            a = store.publish(
                f"td_mc_topic_a_{_SFX}", "content about topic A", agent_name="tester"
            )
            b = store.publish(
                f"td_mc_topic_b_{_SFX}",
                "content about topic A too",
                agent_name="tester",
            )
            lesson_a_id, lesson_b_id = a.lesson_id, b.lesson_id

            store.promote(a.lesson_id, agent_name="tester")  # nothing to merge yet
            assert asyncio.run(_state_of(a.lesson_id)) == [(1, "published")]

            store.promote(b.lesson_id, agent_name="tester")  # sweep fires here

        assert asyncio.run(_state_of(a.lesson_id)) == [(1, "merged_into")]
        assert asyncio.run(_state_of(b.lesson_id)) == [(1, "published")]
    finally:
        for lid in (lesson_a_id, lesson_b_id):
            if lid is not None:
                _cleanup(lid)
        _cleanup_memory_embeddings("fleet-tester")


def test_promote_does_not_merge_dissimilar_published_lessons() -> None:
    lesson_a_id: str | None = None
    lesson_b_id: str | None = None
    try:
        with patch(
            "app.memory.store._embed",
            _patched_embed([_VEC_A, _VEC_B, _VEC_B, _VEC_B]),
        ):
            store = VersionedMemoryStore()
            a = store.publish(
                f"td_mc_dissim_a_{_SFX}", "content A", agent_name="tester"
            )
            b = store.publish(
                f"td_mc_dissim_b_{_SFX}", "content B", agent_name="tester"
            )
            lesson_a_id, lesson_b_id = a.lesson_id, b.lesson_id

            store.promote(a.lesson_id, agent_name="tester")
            store.promote(b.lesson_id, agent_name="tester")

        assert asyncio.run(_state_of(a.lesson_id)) == [(1, "published")]
        assert asyncio.run(_state_of(b.lesson_id)) == [(1, "published")]
    finally:
        for lid in (lesson_a_id, lesson_b_id):
            if lid is not None:
                _cleanup(lid)
        _cleanup_memory_embeddings("fleet-tester")


def test_promote_sweep_disabled_never_merges(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import reset_settings_cache

    monkeypatch.setenv("MEMORY_CONSOLIDATION_ENABLED", "false")
    reset_settings_cache()
    lesson_a_id: str | None = None
    lesson_b_id: str | None = None
    try:
        with patch(
            "app.memory.store._embed",
            # Same corrected order as the positive-merge test above: A's
            # content, B's content (similar to A), then the two promote-
            # sync embeds (values irrelevant).
            _patched_embed([_VEC_A, _VEC_A_SIMILAR, _VEC_B, _VEC_B]),
        ):
            store = VersionedMemoryStore()
            a = store.publish(
                f"td_mc_disabled_a_{_SFX}", "content A", agent_name="tester"
            )
            b = store.publish(
                f"td_mc_disabled_b_{_SFX}", "content A too", agent_name="tester"
            )
            lesson_a_id, lesson_b_id = a.lesson_id, b.lesson_id

            store.promote(a.lesson_id, agent_name="tester")
            store.promote(b.lesson_id, agent_name="tester")

        # Would have merged if enabled (same vectors as the positive test
        # above) — disabled means both stay published.
        assert asyncio.run(_state_of(a.lesson_id)) == [(1, "published")]
        assert asyncio.run(_state_of(b.lesson_id)) == [(1, "published")]
    finally:
        for lid in (lesson_a_id, lesson_b_id):
            if lid is not None:
                _cleanup(lid)
        _cleanup_memory_embeddings("fleet-tester")
        reset_settings_cache()


def test_promote_succeeds_even_if_sweep_raises() -> None:
    """Best-effort: a sweep failure must never break the promotion the
    caller is actually waiting on."""
    lesson_id: str | None = None
    try:
        with (
            patch(
                "app.memory.store._embed",
                _patched_embed([_VEC_A, _VEC_B]),
            ),
            patch(
                "app.fleet.versioned_memory._sweep_and_merge_similar_published",
                side_effect=RuntimeError("db hiccup"),
            ),
        ):
            store = VersionedMemoryStore()
            v1 = store.publish(
                f"td_mc_sweep_fail_{_SFX}", "content", agent_name="tester"
            )
            lesson_id = v1.lesson_id
            promoted = store.promote(v1.lesson_id, agent_name="tester")
            assert promoted.state == "published"
    finally:
        if lesson_id is not None:
            _cleanup(lesson_id)
        _cleanup_memory_embeddings("fleet-tester")


# ---------------------------------------------------------------------------
# Proactive pass — real DB
# ---------------------------------------------------------------------------


def test_consolidate_published_lessons_proposes_a_draft_without_touching_originals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    lesson_a_id: str | None = None
    lesson_b_id: str | None = None
    draft_lesson_id: str | None = None
    try:
        # Only override the one setting this test needs changed — a full
        # MagicMock settings replacement (this test's first version) leaves
        # every OTHER real setting (llm_call_max_retries, model_router, ...)
        # as an un-numeric MagicMock, which the real anthropic SDK's retry
        # logic then fails to compare against an int. monkeypatch.setattr on
        # the real settings singleton keeps everything else genuine, mirroring
        # test_versioned_memory.py's own established convention for this.
        monkeypatch.setattr(get_settings(), "memory_consolidation_enabled", False)
        with patch(
            "app.memory.store._embed",
            # A's content, B's content (similar to A), then the two
            # promote-sync embeds (values irrelevant) — same corrected
            # order as the reactive-sweep tests above. Consolidation is
            # ALSO explicitly disabled during setup (belt and suspenders
            # — this test wants both rows independently 'published'
            # going into the proactive pass, not pre-merged by the
            # reactive sweep).
            _patched_embed([_VEC_A, _VEC_A_SIMILAR, _VEC_B, _VEC_B]),
        ):
            store = VersionedMemoryStore()
            a = store.publish(
                f"td_mc_proactive_a_{_SFX}", "content about X", agent_name="t"
            )
            b = store.publish(
                f"td_mc_proactive_b_{_SFX}", "content about X too", agent_name="t"
            )
            lesson_a_id, lesson_b_id = a.lesson_id, b.lesson_id
            store.promote(a.lesson_id, agent_name="t")
            store.promote(b.lesson_id, agent_name="t")

        assert asyncio.run(_state_of(a.lesson_id)) == [(1, "published")]
        assert asyncio.run(_state_of(b.lesson_id)) == [(1, "published")]

        with (
            patch(
                "app.memory.store._embed",
                _patched_embed([_VEC_A]),  # merged-content embed
            ),
            patch("anthropic.Anthropic") as MockAnthropic,
        ):
            mock_client = MagicMock()
            mock_client.messages.create.return_value = _mock_merge_response(
                "CONSOLIDATED merged content"
            )
            MockAnthropic.return_value = mock_client

            created = store.consolidate_published_lessons()

        matches = [r for r in created if r.content == "CONSOLIDATED merged content"]
        assert len(matches) == 1
        draft = matches[0]
        draft_lesson_id = draft.lesson_id
        assert draft.state == "draft"
        assert draft.supersedes_id in (
            None,
            draft.supersedes_id,
        )  # sanity: field exists
        assert draft.supersedes_id is not None

        # Originals untouched by the proactive pass itself — never
        # auto-published, never auto-superseded.
        assert asyncio.run(_state_of(a.lesson_id)) == [(1, "published")]
        assert asyncio.run(_state_of(b.lesson_id)) == [(1, "published")]
    finally:
        # Real hazard found running this test: consolidate_published_lessons()
        # gives the merged draft a FRESH lesson_id (a distinct lineage from
        # its sources, unlike publish()'s own pairwise merge which reuses
        # the existing lineage's lesson_id) with supersedes_id pointing at
        # the primary source row — deleting that source before the draft in
        # a separate DELETE statement violates the supersedes_id FK
        # (versioned_lessons_supersedes_id_fkey has no ON DELETE clause).
        # Draft first, sources after.
        for lid in (draft_lesson_id, lesson_a_id, lesson_b_id):
            if lid is not None:
                _cleanup(lid)
        _cleanup_memory_embeddings("fleet-t")


def test_consolidate_published_lessons_below_min_cluster_size_proposes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "memory_consolidation_enabled", False)
    lesson_id: str | None = None
    try:
        with patch("app.memory.store._embed", _patched_embed([_VEC_A, _VEC_A])):
            store = VersionedMemoryStore()
            v1 = store.publish(f"td_mc_solo_{_SFX}", "a lone lesson", agent_name="t")
            lesson_id = v1.lesson_id
            store.promote(v1.lesson_id, agent_name="t")

        created = store.consolidate_published_lessons()

        assert created == []
    finally:
        if lesson_id is not None:
            _cleanup(lesson_id)
        _cleanup_memory_embeddings("fleet-t")
