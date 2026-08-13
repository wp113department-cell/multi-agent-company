"""Versioned Memory — Day 11.

Repo research: autogen's MemoryController.add_memo() is pure append (no
similarity check before write), LangGraph's store.BaseStore.put() is a
namespaced key-value upsert that silently overwrites, and this open-hands
checkout has no runtime memory module at all. No repo has a merge-on-conflict
lesson lifecycle — this module is a novel design. Reused, not reinvented:
app.memory.store._embed() (Voyage AI, zero-vector fallback) and its exact
pgvector cosine-distance (<=>) query pattern from Day 6's engineering memory.

This does not replace LessonStore (app/agents/base_graph.py) — that stays the
in-process fast-read cache used for prompt injection during a live run. This
module is the durable, versioned lifecycle layer on top: DRAFT -> PUBLISHED ->
SUPERSEDED / MERGED_INTO -> ARCHIVED.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class VersionedLessonRecord:
    id: int
    lesson_id: str
    topic: str
    content: str
    version: int
    state: str
    supersedes_id: int | None
    created_at: str


def _to_record(row: Any) -> VersionedLessonRecord:
    return VersionedLessonRecord(
        id=row.id,
        lesson_id=row.lesson_id,
        topic=row.topic,
        content=row.content,
        version=row.version,
        state=row.state,
        supersedes_id=row.supersedes_id,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


def _new_isolated_db_engine() -> Any:
    """A throwaway async engine, never the shared app.db.session singleton —
    see app.db.session.new_isolated_async_engine's docstring for why. A
    fresh, disposed-after-use engine per call is always correct."""
    from app.db.session import new_isolated_async_engine

    return new_isolated_async_engine()


@asynccontextmanager
async def _lesson_lock(key: str) -> AsyncIterator[None]:
    """AUDIT_Q_BATCH03 §5 'How synchronized' PARTIAL: app.memory.store's
    _find_near_duplicate closed an identical read-then-write TOCTOU race with
    a `pg_advisory_xact_lock` — that fix was never applied here, even though
    publish() (read _find_most_similar_published, then write _insert) and
    promote()/rollback() (read the current lineage row, then write its state)
    have the exact same shape. Two concurrent publish() calls for the same
    topic could both observe "no similar published lesson" and each insert
    their own version 1; two concurrent promote()/rollback() calls on the
    same lesson_id could race the superseded/published state flips.

    A transaction-scoped `pg_advisory_xact_lock` (store.py's own fix) doesn't
    work here: every helper in this module opens its own throwaway engine/
    session (`_new_isolated_db_engine()` per call, see that function's
    docstring for why this module never reuses the shared app.db.session
    engine), so a lock tied to one of those transactions would already be
    released before the paired read or write runs on the next one. Postgres
    advisory locks are keyed globally (visible to every backend, not just the
    connection that took them) regardless of scope, so a session-scoped
    `pg_advisory_lock`/`pg_advisory_unlock` pair held on one dedicated
    connection for this context manager's lifetime still fully serializes
    concurrent publish()/promote()/rollback() calls sharing the same key,
    even though the actual reads/writes inside happen on other connections.
    -2 is a fixed second key distinguishing this lock's namespace from
    app.memory.store's (category_hash, repo_id) domain, so the two stores'
    lock keyspaces can never collide."""
    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(
                sa_text("SELECT pg_advisory_lock(hashtext(:key)::int, -2)"),
                {"key": key},
            )
            try:
                yield
            finally:
                await session.execute(
                    sa_text("SELECT pg_advisory_unlock(hashtext(:key)::int, -2)"),
                    {"key": key},
                )
    finally:
        await engine.dispose()


async def _find_most_similar_published(vector: list[float]) -> tuple[Any, float] | None:
    from app.memory.store import _ZERO_VECTOR_1536
    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    if vector == _ZERO_VECTOR_1536:
        return None  # no embedding key configured — similarity would be meaningless

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            vec_str = "[" + ",".join(str(v) for v in vector) + "]"
            sql = sa_text("""
                SELECT id, lesson_id, topic, content, version, state, supersedes_id, created_at,
                       1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                FROM versioned_lessons
                WHERE state = 'published' AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT 1
                """)
            row = (await session.execute(sql, {"vec": vec_str})).fetchone()
            return (row, float(row.similarity)) if row is not None else None
    finally:
        await engine.dispose()


async def _insert(
    *,
    lesson_id: str,
    topic: str,
    content: str,
    embedding: list[float],
    version: int,
    state: str,
    supersedes_id: int | None,
) -> Any:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import VersionedLesson

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            row = VersionedLesson(
                lesson_id=lesson_id,
                topic=topic,
                content=content,
                embedding=embedding,
                version=version,
                state=state,
                supersedes_id=supersedes_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row
    finally:
        await engine.dispose()


async def _set_state(row_id: int, state: str) -> None:
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import VersionedLesson

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await session.execute(
                update(VersionedLesson)
                .where(VersionedLesson.id == row_id)
                .values(state=state)
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _most_recent_superseded_for_lineage(lesson_id: str) -> Any:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import VersionedLesson

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return (
                await session.execute(
                    select(VersionedLesson)
                    .where(
                        VersionedLesson.lesson_id == lesson_id,
                        VersionedLesson.state == "superseded",
                    )
                    .order_by(VersionedLesson.version.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
    finally:
        await engine.dispose()


async def _most_recent_draft_for_lineage(lesson_id: str) -> Any:
    """Gap-closure Day 6: the query promote() uses to find what a human
    actually approved promoting — same shape as
    _most_recent_superseded_for_lineage, a separate mockable helper rather
    than inline SQL inside promote() itself, for the same reason every
    other query in this module already is one."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import VersionedLesson

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return (
                await session.execute(
                    select(VersionedLesson)
                    .where(
                        VersionedLesson.lesson_id == lesson_id,
                        VersionedLesson.state == "draft",
                    )
                    .order_by(VersionedLesson.version.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
    finally:
        await engine.dispose()


async def _archive_expired(cutoff: datetime) -> int:
    from sqlalchemy import select, update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import VersionedLesson

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            candidates = (
                (
                    await session.execute(
                        select(VersionedLesson.id).where(
                            VersionedLesson.state.in_(("superseded", "merged_into")),
                            VersionedLesson.created_at < cutoff,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not candidates:
                return 0
            await session.execute(
                update(VersionedLesson)
                .where(VersionedLesson.id.in_(candidates))
                .values(state="archived")
            )
            await session.commit()
            return len(candidates)
    finally:
        await engine.dispose()


async def _sync_to_memory_embeddings(topic: str, content: str, agent_name: str) -> None:
    """Phase 1.2 (MASTER_AGENT_v2.md) — bridge a PUBLISHED versioned lesson into
    memory_embeddings (category="learning") so it's reachable by the exact same
    query path (query_learning_signals) every live agent run already reads
    through. Before this, a curated lesson could complete this module's whole
    DRAFT -> PUBLISHED lifecycle and never be seen by a running agent again —
    confirmed by grep: no code path read a versioned_lessons row back into any
    live inference call. Non-fatal: a sync failure must not break publish()."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.memory.store import embed_learning_signal

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await embed_learning_signal(
                agent_name=agent_name or "knowledge_curator",
                description=content,
                outcome_summary=f"Published versioned lesson (topic: {topic})",
                db=session,
            )
    except Exception:
        logger.warning(
            "versioned_memory: sync to memory_embeddings failed for topic=%s",
            topic,
            exc_info=True,
        )
    finally:
        await engine.dispose()


async def _sweep_and_merge_similar_published(
    promoted_row_id: int, vector: list[float], threshold: float, max_merge: int
) -> list[int]:
    """plan14 Day 3 Task 5 (Memory Consolidation) — N-way generalization of
    publish()'s own pairwise merge-at-draft-time check, applied at promote()
    instead: publish()'s _find_most_similar_published only ever compares a
    NEW draft against the single most-similar EXISTING published lesson at
    the moment that draft is first written, so two lessons that later drift
    into overlapping topics (each published independently, neither one's
    draft-time check ever saw the other) never get compared again after
    that. This runs the same cosine-similarity check, but at promote() — the
    one real moment a lesson actually becomes live/queryable — against every
    OTHER currently-published lesson, not just the one seen at draft time.

    Every match gets flipped to state='merged_into' (the schema's own
    documented lifecycle value — see VersionedLesson's docstring: "DRAFT ->
    PUBLISHED -> SUPERSEDED / MERGED_INTO -> ARCHIVED" — previously declared
    but never actually written by any code path). Never deletes: a merged
    row stays in the table, excluded from state='published' queries exactly
    like a superseded row, until lesson_retention_days eventually archives
    it via the existing archive_expired() job — same reversible-through-the-
    existing-lifecycle property every other state transition in this module
    already has.

    Bounded (LIMIT max_merge) and idempotent by construction: a row already
    flipped to merged_into/superseded is no longer state='published', so a
    second sweep (or the proactive consolidate_published_lessons() pass)
    will never re-select it."""
    from sqlalchemy import text as sa_text, update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import VersionedLesson
    from app.memory.store import _ZERO_VECTOR_1536

    if vector == _ZERO_VECTOR_1536:
        return []

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            vec_str = "[" + ",".join(str(v) for v in vector) + "]"
            sql = sa_text("""
                SELECT id FROM versioned_lessons
                WHERE state = 'published' AND embedding IS NOT NULL AND id != :self_id
                  AND 1 - (embedding <=> CAST(:vec AS vector)) >= :threshold
                LIMIT :max_merge
            """)
            rows = (
                await session.execute(
                    sql,
                    {
                        "self_id": promoted_row_id,
                        "vec": vec_str,
                        "threshold": threshold,
                        "max_merge": max_merge,
                    },
                )
            ).fetchall()
            ids = [r.id for r in rows]
            if not ids:
                return []
            await session.execute(
                update(VersionedLesson)
                .where(VersionedLesson.id.in_(ids))
                .values(state="merged_into")
            )
            await session.commit()
            return ids
    finally:
        await engine.dispose()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    import numpy as np

    va, vb = np.array(a), np.array(b)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def _cluster_by_similarity(
    candidates: list[tuple[int, str, str, list[float]]], threshold: float
) -> list[list[tuple[int, str, str, list[float]]]]:
    """plan14 Day 3 Task 5 — pure, in-memory greedy single-pass clustering
    over a bounded candidate set (see consolidate_published_lessons' own
    LIMIT), same shape as base_graph.py's _group_compressible_lessons but
    using real cosine similarity over embeddings instead of Jaccard token
    overlap, since these rows have real embeddings (unlike LessonStore's
    keyword-only in-process design). Returns every cluster of size >= 2 —
    the caller decides its own minimum size policy."""
    remaining = list(candidates)
    clusters: list[list[tuple[int, str, str, list[float]]]] = []
    while remaining:
        seed = remaining[0]
        group = [seed]
        rest = []
        for other in remaining[1:]:
            if _cosine_similarity(seed[3], other[3]) >= threshold:
                group.append(other)
            else:
                rest.append(other)
        if len(group) >= 2:
            clusters.append(group)
        remaining = rest
    return clusters


async def _merge_via_llm_n(contents: list[str], model: str) -> str:
    """N-way generalization of _merge_via_llm below, for the proactive
    consolidation pass (consolidate_published_lessons) where a cluster can
    have more than 2 members. Runs from a periodic background loop (see
    app/main.py's _versioned_lesson_consolidation_loop), never inside a live
    agent's own turn — unlike _merge_via_llm (called synchronously from
    publish(), itself called from a live agent's record_learning tool call),
    so this deliberately keeps the same plain client construction (SDK
    default timeout, explicit max_retries) rather than needing the isolated
    short-timeout treatment plan14 Day 2 Task 3's LessonStore compression
    required for its own hot-path LLM call."""
    import anthropic

    from app.agents.base import get_effective_api_key
    from app.agents.base_graph import _serialize_content, _text_from_content

    numbered = "\n\n".join(f"Version {i + 1}:\n{c}" for i, c in enumerate(contents))
    prompt = (
        f"The following are {len(contents)} versions of related lessons/insights "
        "learned by AI coding agents, judged similar enough to consolidate. Merge "
        "them into a single, best-of-all lesson: keep everything useful and "
        "distinct from each, remove redundancy, and where they conflict prefer "
        "the more specific or more recently learned guidance.\n\n"
        f"{numbered}\n\n"
        "Respond with ONLY the merged lesson text — no preamble, no JSON, no labels."
    )
    client = anthropic.Anthropic(
        api_key=get_effective_api_key(),
        max_retries=get_settings().llm_call_max_retries,
    )
    r = client.messages.create(
        model=model, max_tokens=768, messages=[{"role": "user", "content": prompt}]
    )
    merged = _text_from_content(_serialize_content(r.content)).strip()
    return merged or max(contents, key=len)  # never publish an empty merge result


async def _fetch_published_candidates(
    max_candidates: int,
) -> list[tuple[int, str, str, list[float]]]:
    """Deliberately an ORM select(), not a raw text() query: pgvector's
    SQLAlchemy Vector type only applies its own result-decoding (wire format
    -> numpy.ndarray) to ORM-mapped column reads. A raw text() SELECT on the
    same column comes back as a plain string (e.g. "[0.1,0.2,...]") with no
    type adapter applied — caught by a real test failure (numpy.linalg.norm
    raising "could not convert string to float" on the literal '[' character
    when the unconverted string was iterated as if it were already a list of
    floats), not assumed correct in advance."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import VersionedLesson

    engine = _new_isolated_db_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            rows = (
                (
                    await session.execute(
                        select(VersionedLesson)
                        .where(
                            VersionedLesson.state == "published",
                            VersionedLesson.embedding.is_not(None),
                        )
                        .order_by(VersionedLesson.created_at.desc())
                        .limit(max_candidates)
                    )
                )
                .scalars()
                .all()
            )
            return [(r.id, r.topic, r.content, list(r.embedding)) for r in rows]
    finally:
        await engine.dispose()


async def _consolidate_published_lessons(
    max_candidates: int, min_cluster_size: int, threshold: float, model: str
) -> list[VersionedLessonRecord]:
    """plan14 Day 3 Task 5 — proactive consolidation pass: scans up to
    `max_candidates` most-recent published lessons, clusters them by real
    cosine similarity, and for each qualifying cluster LLM-merges the
    members into ONE new DRAFT (never auto-published — a human reviews and
    calls the existing memory_promote_lesson tool exactly like any other
    draft; when they do, _sweep_and_merge_similar_published above
    transparently flips the original cluster members to merged_into, since
    the new draft's merged content is embedding-similar to all of them by
    construction — no separate bookkeeping of cluster membership needed).

    Bounded (LIMIT max_candidates keeps the O(n^2) pairwise clustering pass
    cost-bounded), idempotent (a cluster member already merged_into/
    superseded is no longer state='published', so it won't be selected by a
    later run), auditable (each created draft is logged with its source
    cluster size)."""
    from app.memory.store import _embed

    candidates = await _fetch_published_candidates(max_candidates)
    clusters = [
        c
        for c in _cluster_by_similarity(candidates, threshold)
        if len(c) >= min_cluster_size
    ]

    created: list[VersionedLessonRecord] = []
    for cluster in clusters:
        contents = [c[2] for c in cluster]
        merged_content = await _merge_via_llm_n(contents, model)
        merged_vector = await _embed(merged_content)
        # Primary lineage anchor: the most-recently-published member (first
        # in `candidates`' own DESC-by-created_at order that appears in this
        # cluster) — mirrors publish()'s own single-supersedes_id mechanism,
        # unchanged, rather than inventing a multi-parent lineage scheme.
        primary_id = cluster[0][0]
        topic = cluster[0][1]
        row = await _insert(
            lesson_id=str(uuid.uuid4()),
            topic=topic,
            content=merged_content,
            embedding=merged_vector,
            version=1,
            state="draft",
            supersedes_id=primary_id,
        )
        logger.info(
            "versioned_memory: proactive consolidation proposed draft "
            "lesson_id=%s (row #%s) merging %d published lessons: %s",
            row.lesson_id,
            row.id,
            len(cluster),
            [c[0] for c in cluster],
        )
        created.append(_to_record(row))
    return created


async def _merge_via_llm(old_content: str, new_content: str, model: str) -> str:
    import anthropic

    from app.agents.base import get_effective_api_key
    from app.agents.base_graph import _serialize_content, _text_from_content

    prompt = (
        "Two versions of the same lesson/insight were written for the same underlying "
        "topic. Merge them into a single, best-of-both lesson: keep everything useful "
        "from each, remove redundancy, and where they conflict prefer the more specific "
        "or more recently learned guidance.\n\n"
        f"Version A (existing):\n{old_content}\n\nVersion B (new):\n{new_content}\n\n"
        "Respond with ONLY the merged lesson text — no preamble, no JSON, no labels."
    )
    # AUDIT_Q_BATCH08 §38/§66 — explicit, config-driven max_retries, matching
    # app/agents/base_graph.py::_make_client().
    client = anthropic.Anthropic(
        api_key=get_effective_api_key(),
        max_retries=get_settings().llm_call_max_retries,
    )
    r = client.messages.create(
        model=model, max_tokens=512, messages=[{"role": "user", "content": prompt}]
    )
    merged = _text_from_content(_serialize_content(r.content)).strip()
    return merged or new_content  # never publish an empty merge result


class VersionedMemoryStore:
    def publish(
        self, topic: str, content: str, agent_name: str = ""
    ) -> VersionedLessonRecord:
        """File a lesson as a DRAFT — never directly published. Gap-closure
        Day 6 (root cause 3, answers.md Q75/Q93): before this, a single
        agent's self-reported "lesson" from one interaction reached
        state="published" (immediately fleet-wide-searchable, injected into
        every future agent's prompt) with no validation and no human in the
        loop at all. The schema's own DRAFT -> PUBLISHED -> SUPERSEDED /
        MERGED_INTO -> ARCHIVED lifecycle already modeled this distinction —
        publish() simply skipped straight past DRAFT every time. Now it
        doesn't: every call here lands in state="draft" and is invisible to
        both _find_most_similar_published (already filters state='published')
        and query_learning_signals (only ever sees published rows, via
        promote()'s call to _sync_to_memory_embeddings below — not called
        here anymore). A draft only becomes real, queryable fleet memory via
        promote(), which knowledge_curator's APPLY phase calls — itself only
        reachable after a human approves that specific curation action on
        the Fleet Enhancement Dashboard, the same two-phase scan/apply/
        approval gate the platform's other 4 self-improvement agents use.

        If an existing PUBLISHED lesson is semantically similar (cosine
        similarity >= MEMORY_MERGE_SIMILARITY_THRESHOLD), the merge is
        proposed as a new draft version instead of silently overwriting or
        duplicating — the existing published lesson stays exactly as-is,
        visible and in use, until a human approves promoting the merged
        draft, at which point promote() flips the old one to superseded."""
        return asyncio.run(self._publish(topic, content, agent_name))

    async def _publish(
        self, topic: str, content: str, agent_name: str = ""
    ) -> VersionedLessonRecord:
        from app.memory.store import _embed

        s = get_settings()
        vector = await _embed(content)

        async with _lesson_lock(topic):
            match = await _find_most_similar_published(vector)

            if match is None or match[1] < s.memory_merge_similarity_threshold:
                lesson_id = str(uuid.uuid4())
                row = await _insert(
                    lesson_id=lesson_id,
                    topic=topic,
                    content=content,
                    embedding=vector,
                    version=1,
                    state="draft",
                    supersedes_id=None,
                )
                return _to_record(row)

            existing_row, _similarity = match
            merged_content = await _merge_via_llm(
                existing_row.content, content, get_settings().model_router
            )
            merged_vector = await _embed(merged_content)
            merged_row = await _insert(
                lesson_id=existing_row.lesson_id,
                topic=topic,
                content=merged_content,
                embedding=merged_vector,
                version=existing_row.version + 1,
                state="draft",
                supersedes_id=existing_row.id,
            )
            return _to_record(merged_row)

    def promote(self, lesson_id: str, agent_name: str = "") -> VersionedLessonRecord:
        """Gap-closure Day 6: the explicit gate a draft must pass through to
        become real, queryable fleet memory. Called by knowledge_curator's
        APPLY phase (memory_promote_lesson tool) — only reachable after a
        human approves that specific curation action, never autonomously."""
        return asyncio.run(self._promote(lesson_id, agent_name))

    async def _promote(
        self, lesson_id: str, agent_name: str = ""
    ) -> VersionedLessonRecord:
        async with _lesson_lock(lesson_id):
            row = await _most_recent_draft_for_lineage(lesson_id)

            if row is None:
                raise ValueError(
                    f"No draft version to promote for lesson_id={lesson_id!r}"
                )

            if row.supersedes_id is not None:
                await _set_state(row.supersedes_id, "superseded")
            await _set_state(row.id, "published")

        # plan14 Day 3 Task 5 (Memory Consolidation) — N-way sweep for any
        # OTHER currently-published lesson similar enough to merge, run
        # outside the per-lesson lock above (it spans potentially many other
        # lesson_ids) and serialized against concurrent sweeps via its own
        # dedicated lock key, reusing _lesson_lock's own hashtext-keyed
        # mechanism with a fixed string rather than a topic/lesson_id.
        settings = get_settings()
        if settings.memory_consolidation_enabled:
            try:
                async with _lesson_lock("__consolidation_sweep__"):
                    merged_ids = await _sweep_and_merge_similar_published(
                        row.id,
                        list(row.embedding) if row.embedding is not None else [],
                        settings.memory_merge_similarity_threshold,
                        settings.memory_consolidation_max_merge_per_promote,
                    )
                if merged_ids:
                    logger.info(
                        "versioned_memory: promoting lesson_id=%s (row #%s) also "
                        "merged %d other similar published lesson(s): %s",
                        lesson_id,
                        row.id,
                        len(merged_ids),
                        merged_ids,
                    )
            except Exception:
                # Best-effort — a sweep failure must never break the actual
                # promotion the caller is waiting on.
                logger.warning(
                    "versioned_memory: consolidation sweep failed for "
                    "lesson_id=%s (row #%s) — promotion itself still succeeded",
                    lesson_id,
                    row.id,
                    exc_info=True,
                )

        # Non-fatal sync to memory_embeddings — deliberately outside the lock,
        # since it doesn't read or write versioned_lessons state and holding
        # the lock across it would only add unnecessary contention.
        await _sync_to_memory_embeddings(row.topic, row.content, agent_name)

        record = _to_record(row)
        record.state = "published"
        return record

    def consolidate_published_lessons(self) -> list[VersionedLessonRecord]:
        """plan14 Day 3 Task 5 — proactive consolidation pass. Scans currently
        published lessons and proposes merged DRAFTs for qualifying clusters
        (never auto-published — see _consolidate_published_lessons' own
        docstring). Real production wiring: app/main.py's
        _versioned_lesson_consolidation_loop, mirroring archive_expired's own
        existing daily-background-loop pattern exactly."""
        settings = get_settings()
        return asyncio.run(
            _consolidate_published_lessons(
                max_candidates=settings.memory_consolidation_max_candidates,
                min_cluster_size=settings.memory_consolidation_min_cluster_size,
                threshold=settings.memory_merge_similarity_threshold,
                model=settings.model_router,
            )
        )

    def rollback(self, lesson_id: str) -> VersionedLessonRecord:
        return asyncio.run(self._rollback_locked(lesson_id))

    async def _rollback_locked(self, lesson_id: str) -> VersionedLessonRecord:
        """Merges what used to be two separate asyncio.run() calls (a read,
        then a write) in rollback() into one, so the whole read-then-write
        critical section can share a single _lesson_lock — a lock acquired
        and released within one asyncio.run() call cannot span a second,
        later one."""
        async with _lesson_lock(lesson_id):
            prior = await _most_recent_superseded_for_lineage(lesson_id)
            if prior is None:
                raise ValueError(
                    f"No superseded version to roll back to for lesson_id={lesson_id!r}"
                )
            await self._rollback(lesson_id, prior)
        record = _to_record(prior)
        record.state = "published"  # prior was fetched before the flip — reflect the real post-rollback state
        return record

    async def _rollback(self, lesson_id: str, prior: Any) -> None:
        from sqlalchemy import update
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import VersionedLesson

        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    update(VersionedLesson)
                    .where(
                        VersionedLesson.lesson_id == lesson_id,
                        VersionedLesson.state == "published",
                    )
                    .values(state="superseded")
                )
                await session.execute(
                    update(VersionedLesson)
                    .where(VersionedLesson.id == prior.id)
                    .values(state="published")
                )
                await session.commit()
        finally:
            await engine.dispose()

    def archive_expired(self) -> int:
        s = get_settings()
        if s.lesson_retention_days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=s.lesson_retention_days)
        return asyncio.run(_archive_expired(cutoff))


_versioned_memory_singleton: VersionedMemoryStore | None = None


def get_versioned_memory_store() -> VersionedMemoryStore:
    global _versioned_memory_singleton
    if _versioned_memory_singleton is None:
        _versioned_memory_singleton = VersionedMemoryStore()
    return _versioned_memory_singleton
