"""Tests for MASTER_AGENT_v2.md Phase 1.2 — bridge PUBLISHED versioned lessons
into memory_embeddings so a curated lesson is reachable by the same query path
(query_learning_signals) a live agent run actually reads through.

Before this, versioned_memory.py's whole DRAFT -> PUBLISHED lifecycle was
confirmed disconnected from live inference (MASTER_AGENT_v2.md §A.4, System 3)
— a published lesson was written to versioned_lessons and never read by any
running agent again. These tests are DB-connection-free: create_async_engine()
is lazy (no connection until first execute/commit), and embed_learning_signal
itself is mocked, so _sync_to_memory_embeddings never actually touches a
socket — the live-DB, end-to-end version of this test lives in
test_versioned_memory.py alongside the rest of that file's real-Postgres
integration tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.fleet.versioned_memory import VersionedMemoryStore, _sync_to_memory_embeddings


@pytest.mark.asyncio
async def test_sync_calls_embed_learning_signal_with_lesson_content() -> None:
    with patch(
        "app.memory.store.embed_learning_signal", new=AsyncMock()
    ) as mock_embed_signal:
        await _sync_to_memory_embeddings(
            "retry_backoff_tuning",
            "Use exponential backoff, cap at 30s",
            "debugger_agent",
        )

    mock_embed_signal.assert_awaited_once()
    assert mock_embed_signal.await_args is not None
    kwargs = mock_embed_signal.await_args.kwargs
    assert kwargs["agent_name"] == "debugger_agent"
    assert kwargs["description"] == "Use exponential backoff, cap at 30s"
    assert "retry_backoff_tuning" in kwargs["outcome_summary"]


@pytest.mark.asyncio
async def test_sync_falls_back_to_knowledge_curator_when_agent_name_blank() -> None:
    with patch(
        "app.memory.store.embed_learning_signal", new=AsyncMock()
    ) as mock_embed_signal:
        await _sync_to_memory_embeddings("topic", "content", "")

    assert mock_embed_signal.await_args is not None
    assert mock_embed_signal.await_args.kwargs["agent_name"] == "knowledge_curator"


@pytest.mark.asyncio
async def test_sync_failure_is_non_fatal() -> None:
    """A broken memory_embeddings bridge must never break a lesson publish."""
    with patch(
        "app.memory.store.embed_learning_signal",
        new=AsyncMock(side_effect=RuntimeError("db down")),
    ):
        await _sync_to_memory_embeddings("topic", "content", "tester")
    # No exception propagated — test passing at all is the assertion.


@pytest.mark.asyncio
async def test_publish_fresh_topic_triggers_sync_to_memory_embeddings() -> None:
    """_publish's fresh-topic path (no similar PUBLISHED lesson found) must
    call the memory_embeddings bridge exactly once, with the real lesson
    content and the real agent_name — proving the agent_name parameter
    (previously silently dropped between publish() and _publish()) now
    actually reaches the sync call."""
    store = VersionedMemoryStore()

    fake_row = AsyncMock()
    fake_row.id = 1
    fake_row.lesson_id = "lesson-abc"
    fake_row.topic = "td_sync_topic"
    fake_row.content = "a brand new lesson"
    fake_row.version = 1
    fake_row.state = "published"
    fake_row.supersedes_id = None
    fake_row.created_at = None

    with (
        patch("app.memory.store._embed", new=AsyncMock(return_value=[0.1] * 1536)),
        patch(
            "app.fleet.versioned_memory._find_most_similar_published",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.fleet.versioned_memory._insert", new=AsyncMock(return_value=fake_row)
        ),
        patch(
            "app.fleet.versioned_memory._sync_to_memory_embeddings", new=AsyncMock()
        ) as mock_sync,
    ):
        result = await store._publish(
            "td_sync_topic", "a brand new lesson", agent_name="debugger_agent"
        )

    assert result.state == "published"
    mock_sync.assert_awaited_once_with(
        "td_sync_topic", "a brand new lesson", "debugger_agent"
    )
