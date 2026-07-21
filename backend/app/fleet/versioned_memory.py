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
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings


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
    see feedback_asyncio_isolated_engine: reusing one engine across multiple
    asyncio.run() calls in the same process raises 'attached to a different
    loop'. A fresh, disposed-after-use engine per call is always correct."""
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


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
            sql = sa_text(
                """
                SELECT id, lesson_id, topic, content, version, state, supersedes_id, created_at,
                       1 - (embedding <=> CAST(:vec AS vector)) AS similarity
                FROM versioned_lessons
                WHERE state = 'published' AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT 1
                """
            )
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
            await session.execute(update(VersionedLesson).where(VersionedLesson.id == row_id).values(state=state))
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
                    .where(VersionedLesson.lesson_id == lesson_id, VersionedLesson.state == "superseded")
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
                await session.execute(
                    select(VersionedLesson.id).where(
                        VersionedLesson.state.in_(("superseded", "merged_into")),
                        VersionedLesson.created_at < cutoff,
                    )
                )
            ).scalars().all()
            if not candidates:
                return 0
            await session.execute(
                update(VersionedLesson).where(VersionedLesson.id.in_(candidates)).values(state="archived")
            )
            await session.commit()
            return len(candidates)
    finally:
        await engine.dispose()


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
    client = anthropic.Anthropic(api_key=get_effective_api_key())
    r = client.messages.create(model=model, max_tokens=512, messages=[{"role": "user", "content": prompt}])
    merged = _text_from_content(_serialize_content(r.content)).strip()
    return merged or new_content  # never publish an empty merge result


class VersionedMemoryStore:
    def publish(self, topic: str, content: str, agent_name: str = "") -> VersionedLessonRecord:
        """Publish a lesson. If an existing PUBLISHED lesson is semantically
        similar (cosine similarity >= MEMORY_MERGE_SIMILARITY_THRESHOLD),
        merges instead of silently overwriting or duplicating."""
        return asyncio.run(self._publish(topic, content))

    async def _publish(self, topic: str, content: str) -> VersionedLessonRecord:
        from app.memory.store import _embed

        s = get_settings()
        vector = await _embed(content)
        match = await _find_most_similar_published(vector)

        if match is None or match[1] < s.memory_merge_similarity_threshold:
            lesson_id = str(uuid.uuid4())
            row = await _insert(
                lesson_id=lesson_id, topic=topic, content=content, embedding=vector,
                version=1, state="published", supersedes_id=None,
            )
            return _to_record(row)

        existing_row, _similarity = match
        v2 = await _insert(
            lesson_id=existing_row.lesson_id, topic=topic, content=content, embedding=vector,
            version=existing_row.version + 1, state="draft", supersedes_id=existing_row.id,
        )
        merged_content = await _merge_via_llm(existing_row.content, content, get_settings().model_planner)
        merged_vector = await _embed(merged_content)
        merged_row = await _insert(
            lesson_id=existing_row.lesson_id, topic=topic, content=merged_content, embedding=merged_vector,
            version=v2.version + 1, state="published", supersedes_id=existing_row.id,
        )
        await _set_state(existing_row.id, "superseded")
        await _set_state(v2.id, "merged_into")
        return _to_record(merged_row)

    def rollback(self, lesson_id: str) -> VersionedLessonRecord:
        prior = asyncio.run(_most_recent_superseded_for_lineage(lesson_id))
        if prior is None:
            raise ValueError(f"No superseded version to roll back to for lesson_id={lesson_id!r}")
        asyncio.run(self._rollback(lesson_id, prior))
        record = _to_record(prior)
        record.state = "published"  # prior was fetched before the flip — reflect the real post-rollback state
        return record

    async def _rollback(self, lesson_id: str, prior: Any) -> None:
        from sqlalchemy import select, update
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import VersionedLesson

        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    update(VersionedLesson)
                    .where(VersionedLesson.lesson_id == lesson_id, VersionedLesson.state == "published")
                    .values(state="superseded")
                )
                await session.execute(
                    update(VersionedLesson).where(VersionedLesson.id == prior.id).values(state="published")
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
