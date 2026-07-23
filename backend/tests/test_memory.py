"""Tests for Engineering Memory v1 — embedding, storage, similarity query."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.memory.store import (
    _build_outcome_text,
    _ZERO_VECTOR_1536,
    embed_learning_signal,
    embed_task_outcome,
    format_memory_context,
    query_learning_signals,
    query_similar_tasks,
)

# ---- Text building ----


def test_build_outcome_text_includes_outcome() -> None:
    text = _build_outcome_text(
        "add button", "button added", "completed", ["frontend/button.tsx"]
    )
    assert "completed" in text
    assert "add button" in text
    assert "button added" in text
    assert "frontend/button.tsx" in text


def test_build_outcome_text_caps_files_at_20() -> None:
    files = [f"file_{i}.py" for i in range(30)]
    text = _build_outcome_text("task", "done", "completed", files)
    # Only first 20 files should appear
    assert "file_19.py" in text
    assert "file_20.py" not in text


# ---- Zero vector fallback ----


def test_zero_vector_is_1536_dims() -> None:
    assert len(_ZERO_VECTOR_1536) == 1536
    assert all(v == 0.0 for v in _ZERO_VECTOR_1536)


@pytest.mark.asyncio
async def test_embed_returns_zero_vector_when_no_api_key() -> None:
    """When VOYAGE_API_KEY is empty, _embed() returns the zero vector."""
    from app.memory.store import _embed

    with patch("app.memory.store.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            voyage_api_key="", voyage_model="voyage-code-2"
        )
        vector = await _embed("some description")

    assert vector == _ZERO_VECTOR_1536


# ---- embed_task_outcome ----


@pytest.mark.asyncio
async def test_embed_task_outcome_inserts_row() -> None:
    """embed_task_outcome creates a MemoryEmbedding row and commits."""
    mock_db = AsyncMock()
    mock_row = MagicMock()
    mock_row.id = 42

    # Simulate db.refresh loading the ID
    async def fake_refresh(obj: Any) -> None:
        obj.id = 42

    mock_db.refresh = fake_refresh
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    with patch("app.memory.store.get_settings") as ms, patch(
        "app.memory.store._embed"
    ) as mock_embed:
        ms.return_value = MagicMock(
            memory_enabled=True, voyage_api_key="", voyage_model="m"
        )
        mock_embed.return_value = _ZERO_VECTOR_1536

        result = await embed_task_outcome(  # noqa: F841
            task_id="task-123",
            description="Add login endpoint",
            summary="Login endpoint added",
            outcome="completed",
            files_changed=["backend/api/auth.py"],
            db=mock_db,
        )

    assert mock_db.add.called
    assert mock_db.commit.called


@pytest.mark.asyncio
async def test_embed_task_outcome_disabled_returns_none() -> None:
    """When MEMORY_ENABLED=false, embed_task_outcome returns None without touching DB."""
    mock_db = AsyncMock()

    with patch("app.memory.store.get_settings") as ms:
        ms.return_value = MagicMock(memory_enabled=False)
        result = await embed_task_outcome(
            task_id="task-1",
            description="test",
            summary="done",
            outcome="completed",
            files_changed=[],
            db=mock_db,
        )

    assert result is None
    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_embed_task_outcome_db_error_returns_none() -> None:
    """If DB commit raises, embed_task_outcome catches, rollbacks, and returns None."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()  # SQLAlchemy add() is synchronous
    mock_db.commit = AsyncMock(side_effect=RuntimeError("DB is down"))
    mock_db.rollback = AsyncMock()

    with patch("app.memory.store.get_settings") as ms, patch(
        "app.memory.store._embed"
    ) as mock_embed:
        ms.return_value = MagicMock(
            memory_enabled=True, voyage_api_key="", voyage_model="m"
        )
        mock_embed.return_value = _ZERO_VECTOR_1536

        result = await embed_task_outcome(
            task_id="task-fail",
            description="fail task",
            summary="it broke",
            outcome="blocked",
            files_changed=[],
            db=mock_db,
        )

    assert result is None
    assert mock_db.rollback.called


# ---- query_similar_tasks ----


@pytest.mark.asyncio
async def test_query_similar_tasks_disabled_returns_empty() -> None:
    """When MEMORY_ENABLED=false, query_similar_tasks returns []."""
    mock_db = AsyncMock()
    with patch("app.memory.store.get_settings") as ms:
        ms.return_value = MagicMock(memory_enabled=False)
        results = await query_similar_tasks("fix auth bug", mock_db)
    assert results == []


@pytest.mark.asyncio
async def test_query_similar_tasks_no_api_key_returns_empty() -> None:
    """Without VOYAGE_API_KEY, query returns [] (zero vector, skip DB query)."""
    mock_db = AsyncMock()
    with patch("app.memory.store.get_settings") as ms, patch(
        "app.memory.store._embed"
    ) as mock_embed:
        ms.return_value = MagicMock(
            memory_enabled=True, memory_top_k=3, voyage_api_key=""
        )
        mock_embed.return_value = _ZERO_VECTOR_1536

        results = await query_similar_tasks("fix auth bug", mock_db)

    assert results == []
    mock_db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_query_similar_tasks_returns_formatted_rows() -> None:
    """query_similar_tasks returns list of dicts with expected keys."""
    mock_db = AsyncMock()

    fake_row = MagicMock()
    fake_row.task_id = "task-99"
    fake_row.epic_id = None
    fake_row.outcome = "completed"
    fake_row.description = "add login"
    fake_row.summary = "login added"
    fake_row.files_changed = ["auth/login.py"]
    fake_row.similarity = 0.92

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [fake_row]
    mock_db.execute = AsyncMock(return_value=mock_result)

    non_zero = [0.1] * 1536

    with patch("app.memory.store.get_settings") as ms, patch(
        "app.memory.store._embed"
    ) as mock_embed:
        ms.return_value = MagicMock(
            memory_enabled=True,
            memory_top_k=3,
            voyage_api_key="key",
            voyage_model="voyage-code-2",
        )
        mock_embed.return_value = non_zero
        results = await query_similar_tasks("add authentication", mock_db, top_k=3)

    assert len(results) == 1
    assert results[0]["task_id"] == "task-99"
    assert results[0]["outcome"] == "completed"
    assert results[0]["similarity"] == pytest.approx(0.92)


# ---- format_memory_context ----


def test_format_memory_context_empty_list() -> None:
    assert format_memory_context([]) == ""


def test_format_memory_context_includes_task_info() -> None:
    tasks = [
        {
            "task_id": "t-1",
            "epic_id": None,
            "outcome": "completed",
            "description": "Add login endpoint",
            "summary": "Implemented JWT login",
            "files_changed": ["auth/login.py"],
            "similarity": 0.95,
        }
    ]
    ctx = format_memory_context(tasks)
    assert "t-1" in ctx
    assert "completed" in ctx
    assert "Implemented JWT login" in ctx
    assert "0.950" in ctx


def test_format_memory_context_multiple_tasks() -> None:
    tasks = [
        {
            "task_id": f"t-{i}",
            "epic_id": None,
            "outcome": "completed",
            "description": "task",
            "summary": "done",
            "files_changed": [],
            "similarity": 0.9,
        }
        for i in range(3)
    ]
    ctx = format_memory_context(tasks)
    assert "t-0" in ctx
    assert "t-2" in ctx


# ---- embed_learning_signal / query_learning_signals ----
# Gap-closure (files/GAPS_ALL_FILES_REPORT.md, 2026-07-23): Doc 11's 4th
# memory category ("learning") was schema-supported (migration 010) but
# never actually written anywhere — grep confirmed zero real writes.


@pytest.mark.asyncio
async def test_embed_learning_signal_inserts_row_with_learning_category() -> None:
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    async def fake_refresh(obj: Any) -> None:
        obj.id = 7

    mock_db.refresh = fake_refresh

    with patch("app.memory.store.get_settings") as ms, patch(
        "app.memory.store._embed"
    ) as mock_embed:
        ms.return_value = MagicMock(memory_enabled=True)
        mock_embed.return_value = _ZERO_VECTOR_1536

        result = await embed_learning_signal(
            agent_name="agent_performance_reviewer",
            description="Tighten reviewer prompt to reduce false positives",
            outcome_summary="Applied and committed role prompt change",
            db=mock_db,
        )

    assert mock_db.add.called
    assert mock_db.commit.called
    added_row = mock_db.add.call_args.args[0]
    assert added_row.category == "learning"
    assert added_row.outcome == "learning"
    assert added_row.task_id == "fleet-agent_performance_reviewer"
    assert result is not None


@pytest.mark.asyncio
async def test_embed_learning_signal_disabled_returns_none() -> None:
    mock_db = AsyncMock()
    with patch("app.memory.store.get_settings") as ms:
        ms.return_value = MagicMock(memory_enabled=False)
        result = await embed_learning_signal(
            agent_name="knowledge_curator",
            description="d",
            outcome_summary="o",
            db=mock_db,
        )
    assert result is None
    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_embed_learning_signal_db_error_returns_none() -> None:
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock(side_effect=RuntimeError("DB is down"))
    mock_db.rollback = AsyncMock()

    with patch("app.memory.store.get_settings") as ms, patch(
        "app.memory.store._embed"
    ) as mock_embed:
        ms.return_value = MagicMock(memory_enabled=True)
        mock_embed.return_value = _ZERO_VECTOR_1536

        result = await embed_learning_signal(
            agent_name="agent_debugger",
            description="d",
            outcome_summary="o",
            db=mock_db,
        )

    assert result is None
    assert mock_db.rollback.called


@pytest.mark.asyncio
async def test_query_learning_signals_disabled_returns_empty() -> None:
    mock_db = AsyncMock()
    with patch("app.memory.store.get_settings") as ms:
        ms.return_value = MagicMock(memory_enabled=False)
        results = await query_learning_signals("retry loop tuning", mock_db)
    assert results == []


@pytest.mark.asyncio
async def test_query_learning_signals_returns_formatted_rows() -> None:
    mock_db = AsyncMock()
    fake_row = MagicMock()
    fake_row.task_id = "fleet-quality_auditor"
    fake_row.description = "Fixed secrets_scan false negative"
    fake_row.summary = "Applied and committed"
    fake_row.similarity = 0.87

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [fake_row]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.memory.store.get_settings") as ms, patch(
        "app.memory.store._embed"
    ) as mock_embed:
        ms.return_value = MagicMock(memory_enabled=True)
        mock_embed.return_value = [0.1] * 1536

        results = await query_learning_signals("secrets scan", mock_db)

    assert len(results) == 1
    assert results[0]["agent_name"] == "quality_auditor"
    assert results[0]["action"] == "Fixed secrets_scan false negative"
    assert results[0]["similarity"] == 0.87
