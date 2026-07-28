"""Tests for MASTER_AGENT_v2.md Phase 1.3 — memory_hook_node also queries
memory_embeddings (DB-backed, semantic, cross-process, survives restarts),
not just the in-process, keyword-only, per-process LessonStore.

query_memory_context/query_memory_context_sync/format_full_memory_context all
live in app/memory/store.py; the LangGraph wiring itself
(base_graph.py::memory_hook_node) is covered by
tests/test_day0_capabilities.py::TestMemoryHookNodeFires — these tests cover
the new store-layer functions those existing tests now transitively exercise.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.memory.store import (
    format_full_memory_context,
    query_memory_context,
    query_memory_context_sync,
)

# ---------------------------------------------------------------------------
# query_memory_context — combines the three existing async queries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_memory_context_combines_three_sources() -> None:
    mock_db = AsyncMock()

    with (
        patch(
            "app.memory.store.query_similar_tasks",
            new=AsyncMock(return_value=[{"task_id": "t-1"}]),
        ),
        patch(
            "app.memory.store.query_failures",
            new=AsyncMock(return_value=[{"task_id": "t-2"}]),
        ),
        patch(
            "app.memory.store.query_learning_signals",
            new=AsyncMock(return_value=[{"agent_name": "qa"}]),
        ),
    ):
        result = await query_memory_context("fix auth bug", mock_db, top_k=5)

    assert result["tasks"] == [{"task_id": "t-1"}]
    assert result["failures"] == [{"task_id": "t-2"}]
    assert result["learnings"] == [{"agent_name": "qa"}]


# ---------------------------------------------------------------------------
# query_memory_context_sync — the sync bridge memory_hook_node actually calls
# ---------------------------------------------------------------------------


def test_query_memory_context_sync_returns_async_result() -> None:
    fake_result = {"tasks": [{"task_id": "t-1"}], "failures": [], "learnings": []}

    with patch(
        "app.memory.store.query_memory_context", new=AsyncMock(return_value=fake_result)
    ):
        result = query_memory_context_sync("fix auth bug")

    assert result == fake_result


def test_query_memory_context_sync_returns_empty_on_failure() -> None:
    """A broken DB/engine must never raise into the calling LangGraph node."""
    with patch(
        "app.memory.store.query_memory_context",
        new=AsyncMock(side_effect=RuntimeError("db down")),
    ):
        result = query_memory_context_sync("fix auth bug")

    assert result == {"tasks": [], "failures": [], "learnings": [], "procedures": []}


# ---------------------------------------------------------------------------
# format_full_memory_context
# ---------------------------------------------------------------------------


def test_format_full_memory_context_empty_everything() -> None:
    assert format_full_memory_context([], [], []) == ""


def test_format_full_memory_context_omits_empty_sections() -> None:
    tasks = [
        {
            "task_id": "t-1",
            "epic_id": None,
            "outcome": "completed",
            "description": "d",
            "summary": "s",
            "files_changed": [],
            "similarity": 0.9,
        }
    ]
    out = format_full_memory_context(tasks, [], [])
    assert "Similar past tasks" in out
    assert "Similar past failures" not in out
    assert "Fleet learning signals" not in out


def test_format_full_memory_context_includes_all_three_sections() -> None:
    tasks = [
        {
            "task_id": "t-1",
            "epic_id": None,
            "outcome": "completed",
            "description": "d",
            "summary": "s",
            "files_changed": [],
            "similarity": 0.9,
        }
    ]
    failures = [
        {
            "task_id": "t-2",
            "epic_id": None,
            "error": "NullPointerException",
            "root_cause": "missing null check",
            "similarity": 0.85,
        }
    ]
    learnings = [
        {
            "agent_name": "debugger_agent",
            "action": "added retry with backoff",
            "outcome": "fixed flaky test",
            "similarity": 0.8,
        }
    ]
    out = format_full_memory_context(tasks, failures, learnings)
    assert "Similar past tasks" in out
    assert "Similar past failures" in out
    assert "NullPointerException" in out
    assert "missing null check" in out
    assert "Fleet learning signals" in out
    assert "debugger_agent" in out
    assert "added retry with backoff" in out
