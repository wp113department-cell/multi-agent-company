"""Day 11 — versioned_memory.py: DRAFT -> PUBLISHED -> SUPERSEDED / MERGED_INTO
-> ARCHIVED lesson lifecycle with merge-on-conflict.

No repo in /repos has this pattern (verified during Day 11 planning — autogen
appends, LangGraph's store overwrites, open-hands has no runtime memory
module), so this is entirely new logic and gets tested end-to-end against the
real DB (migration 014) with mocked embeddings (no VOYAGE_API_KEY in this
environment) and a mocked Anthropic merge call.

_embed is imported via a fresh `from app.memory.store import _embed` inside
versioned_memory._publish() on every call, so patching
app.memory.store._embed directly (not a local re-export) is what actually
takes effect — same reasoning documented in test_prompt_registry.py for why
patching a local-import target doesn't work.
"""
from __future__ import annotations

import asyncio
import random
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.fleet.versioned_memory import VersionedMemoryStore, get_versioned_memory_store

_RNG = random.Random(42)
_BASE_VECTOR = [_RNG.random() for _ in range(1536)]
_SIMILAR_VECTOR = [v + 0.0001 for v in _BASE_VECTOR]
_DIFFERENT_VECTOR = [_RNG.random() for _ in range(1536)]


def _cleanup(*lesson_ids: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import VersionedLesson

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(delete(VersionedLesson).where(VersionedLesson.lesson_id.in_(lesson_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _mock_merge_response(text: str) -> Any:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _patched_embed(vectors: list[list[float]]) -> Any:
    """Returns an async function that yields vectors in call order."""
    queue = iter(vectors)

    async def _fake_embed(text: str) -> list[float]:
        return next(queue)

    return _fake_embed


def test_publish_fresh_topic_creates_version_1_published() -> None:
    with patch("app.memory.store._embed", _patched_embed([_DIFFERENT_VECTOR])):
        store = VersionedMemoryStore()
        result = store.publish("td_vm_fresh_topic", "a brand new lesson", agent_name="tester")
    try:
        assert result.version == 1
        assert result.state == "published"
        assert result.supersedes_id is None
    finally:
        _cleanup(result.lesson_id)


def test_publish_similar_content_triggers_merge_not_duplicate() -> None:
    with patch("app.memory.store._embed", _patched_embed([_BASE_VECTOR, _SIMILAR_VECTOR, _BASE_VECTOR])), patch(
        "anthropic.Anthropic"
    ) as MockAnthropic:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_merge_response("MERGED best-of-both content")
        MockAnthropic.return_value = mock_client

        store = VersionedMemoryStore()
        v1 = store.publish("td_vm_merge_topic", "v1: validate inputs at the boundary", agent_name="tester")
        try:
            v2_result = store.publish("td_vm_merge_topic", "v2: validate inputs, log rejections", agent_name="tester")

            assert v2_result.lesson_id == v1.lesson_id  # same lineage — merged, not a fresh publish
            assert v2_result.state == "published"
            assert v2_result.content == "MERGED best-of-both content"
            assert v2_result.version == 3  # v1=1, v2(draft)=2, merged=3

            mock_client.messages.create.assert_called_once()
        finally:
            _cleanup(v1.lesson_id)


def test_publish_similar_content_flips_prior_states_correctly() -> None:
    with patch("app.memory.store._embed", _patched_embed([_BASE_VECTOR, _SIMILAR_VECTOR, _BASE_VECTOR])), patch(
        "anthropic.Anthropic"
    ) as MockAnthropic:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_merge_response("MERGED content")
        MockAnthropic.return_value = mock_client

        store = VersionedMemoryStore()
        v1 = store.publish("td_vm_state_flip", "v1 content", agent_name="tester")
        try:
            store.publish("td_vm_state_flip", "v2 content", agent_name="tester")

            from sqlalchemy import select
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            from app.config import get_settings
            from app.db.models import VersionedLesson

            async def _query() -> list[tuple[int, str]]:
                engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                        rows = (
                            await session.execute(
                                select(VersionedLesson)
                                .where(VersionedLesson.lesson_id == v1.lesson_id)
                                .order_by(VersionedLesson.version.asc())
                            )
                        ).scalars().all()
                        return [(r.version, r.state) for r in rows]
                finally:
                    await engine.dispose()

            states = asyncio.run(_query())
            assert states == [(1, "superseded"), (2, "merged_into"), (3, "published")]
        finally:
            _cleanup(v1.lesson_id)


def test_publish_different_topic_does_not_merge() -> None:
    with patch("app.memory.store._embed", _patched_embed([_BASE_VECTOR, _DIFFERENT_VECTOR])):
        store = VersionedMemoryStore()
        v1 = store.publish("td_vm_topic_a", "content about topic A", agent_name="tester")
        try:
            v2 = store.publish("td_vm_topic_b", "content about topic B", agent_name="tester")
            assert v2.lesson_id != v1.lesson_id
            assert v2.version == 1
            assert v2.state == "published"
        finally:
            _cleanup(v1.lesson_id, v2.lesson_id)


def test_publish_with_zero_vector_never_merges() -> None:
    """No VOYAGE_API_KEY configured in this environment -> _embed returns the
    real zero-vector fallback -> similarity search must be skipped entirely,
    matching app.memory.store's own zero-vector-skips-DB-call convention."""
    store = VersionedMemoryStore()
    v1 = store.publish("td_vm_zero_vector_a", "content A", agent_name="tester")
    try:
        v2 = store.publish("td_vm_zero_vector_b", "content B", agent_name="tester")
        try:
            assert v1.lesson_id != v2.lesson_id
            assert v1.version == 1
            assert v2.version == 1
        finally:
            _cleanup(v2.lesson_id)
    finally:
        _cleanup(v1.lesson_id)


def test_rollback_restores_previous_published_version_and_state() -> None:
    with patch("app.memory.store._embed", _patched_embed([_BASE_VECTOR, _SIMILAR_VECTOR, _BASE_VECTOR])), patch(
        "anthropic.Anthropic"
    ) as MockAnthropic:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_merge_response("merged content")
        MockAnthropic.return_value = mock_client

        store = VersionedMemoryStore()
        v1 = store.publish("td_vm_rollback", "original content", agent_name="tester")
        try:
            store.publish("td_vm_rollback", "conflicting content", agent_name="tester")

            restored = store.rollback(v1.lesson_id)
            assert restored.content == "original content"
            assert restored.state == "published"  # reflects the post-rollback state, not the stale pre-flip one
        finally:
            _cleanup(v1.lesson_id)


def test_rollback_with_no_superseded_version_raises() -> None:
    with pytest.raises(ValueError, match="No superseded version"):
        VersionedMemoryStore().rollback("td_vm_never_existed_lesson_id")


def test_archive_expired_marks_old_superseded_rows_archived() -> None:
    with patch("app.memory.store._embed", _patched_embed([_BASE_VECTOR, _SIMILAR_VECTOR, _BASE_VECTOR])), patch(
        "anthropic.Anthropic"
    ) as MockAnthropic:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_merge_response("merged content")
        MockAnthropic.return_value = mock_client

        store = VersionedMemoryStore()
        v1 = store.publish("td_vm_archive", "original content", agent_name="tester")
        try:
            store.publish("td_vm_archive", "conflicting content", agent_name="tester")

            from datetime import datetime, timezone

            from sqlalchemy import update
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            from app.config import get_settings
            from app.db.models import VersionedLesson

            async def _backdate() -> None:
                engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                        await session.execute(
                            update(VersionedLesson)
                            .where(VersionedLesson.lesson_id == v1.lesson_id)
                            .values(created_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
                        )
                        await session.commit()
                finally:
                    await engine.dispose()

            asyncio.run(_backdate())

            archived_count = store.archive_expired()
            assert archived_count >= 2  # the superseded v1 row and the merged_into v2 row
        finally:
            _cleanup(v1.lesson_id)


def test_archive_expired_disabled_when_retention_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "lesson_retention_days", 0)
    store = VersionedMemoryStore()
    assert store.archive_expired() == 0


def test_get_versioned_memory_store_returns_singleton() -> None:
    assert get_versioned_memory_store() is get_versioned_memory_store()
