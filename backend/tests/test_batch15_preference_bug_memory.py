"""Tests for AUDIT_Q_BATCH15 §74/§113 (preference) and §75/§105/§112 (bug)
gap-closure — dedicated memory categories with their own embed/query path,
mirroring test_procedural_memory.py's established mock-DB convention for
app/memory/store.py.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.memory.store import (
    embed_bug,
    embed_preference,
    format_full_memory_context,
    query_bugs,
    query_preferences,
)

# ---------------------------------------------------------------------------
# embed_preference / query_preferences
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_preference_inserts_row_with_preference_category() -> None:
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    async def fake_refresh(obj: Any) -> None:
        obj.id = 1

    mock_db.refresh = fake_refresh

    with (
        patch("app.memory.store.get_settings") as ms,
        patch("app.memory.store._embed") as mock_embed,
    ):
        ms.return_value = MagicMock(memory_enabled=True)
        mock_embed.return_value = [0.0] * 1536

        result = await embed_preference(
            task_id="chat-1",
            preference="always use f-strings, never .format()",
            scope="style",
            db=mock_db,
        )

    assert mock_db.add.called
    row = mock_db.add.call_args.args[0]
    assert row.category == "preference"
    assert row.outcome == "preference"
    assert row.description == "always use f-strings, never .format()"
    assert row.summary == "scope=style"
    assert result is not None


@pytest.mark.asyncio
async def test_embed_preference_disabled_returns_none() -> None:
    mock_db = AsyncMock()
    with patch("app.memory.store.get_settings") as ms:
        ms.return_value = MagicMock(memory_enabled=False)
        result = await embed_preference(
            task_id="t", preference="p", scope="style", db=mock_db
        )
    assert result is None
    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_query_preferences_returns_formatted_rows() -> None:
    mock_db = AsyncMock()
    fake_row = MagicMock()
    fake_row.task_id = "chat-1"
    fake_row.epic_id = None
    fake_row.description = "always use f-strings"
    fake_row.summary = "scope=style"
    fake_row.similarity = 0.88

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [fake_row]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.memory.store.get_settings") as ms,
        patch("app.memory.store._embed") as mock_embed,
    ):
        ms.return_value = MagicMock(memory_enabled=True)
        mock_embed.return_value = [0.1] * 1536
        results = await query_preferences("string formatting style", mock_db)

    assert len(results) == 1
    assert results[0]["preference"] == "always use f-strings"
    assert results[0]["scope"] == "style"
    assert results[0]["similarity"] == pytest.approx(0.88)


# ---------------------------------------------------------------------------
# embed_bug / query_bugs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_bug_inserts_row_with_bug_category() -> None:
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    async def fake_refresh(obj: Any) -> None:
        obj.id = 1

    mock_db.refresh = fake_refresh

    with (
        patch("app.memory.store.get_settings") as ms,
        patch("app.memory.store._embed") as mock_embed,
    ):
        ms.return_value = MagicMock(memory_enabled=True)
        mock_embed.return_value = [0.0] * 1536

        result = await embed_bug(
            task_id="known-issue-1",
            issue="race condition in shared connection pool under load",
            severity="high",
            db=mock_db,
        )

    assert mock_db.add.called
    row = mock_db.add.call_args.args[0]
    assert row.category == "bug"
    assert row.outcome == "bug"
    assert "race condition" in row.description
    assert row.summary == "severity=high"
    assert result is not None


@pytest.mark.asyncio
async def test_query_bugs_returns_formatted_rows() -> None:
    mock_db = AsyncMock()
    fake_row = MagicMock()
    fake_row.task_id = "known-issue-1"
    fake_row.epic_id = None
    fake_row.description = "race condition under load"
    fake_row.summary = "severity=high"
    fake_row.similarity = 0.77

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [fake_row]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.memory.store.get_settings") as ms,
        patch("app.memory.store._embed") as mock_embed,
    ):
        ms.return_value = MagicMock(memory_enabled=True)
        mock_embed.return_value = [0.1] * 1536
        results = await query_bugs("connection pool bug", mock_db)

    assert len(results) == 1
    assert results[0]["issue"] == "race condition under load"
    assert results[0]["severity"] == "high"


# ---------------------------------------------------------------------------
# format_full_memory_context — preferences/bugs sections
# ---------------------------------------------------------------------------


def test_format_full_memory_context_includes_preferences_and_bugs_sections() -> None:
    preferences = [
        {
            "preference": "always use pytest fixtures over setUp",
            "scope": "testing",
            "similarity": 0.9,
        }
    ]
    bugs = [
        {
            "task_id": "known-issue-1",
            "issue": "race condition in connection pool",
            "severity": "high",
            "similarity": 0.85,
        }
    ]
    out = format_full_memory_context([], [], [], [], preferences, bugs)
    assert "Stated preferences" in out
    assert "pytest fixtures" in out
    assert "Known bugs" in out
    assert "race condition in connection pool" in out


def test_format_full_memory_context_omits_preferences_and_bugs_when_empty() -> None:
    out = format_full_memory_context([], [], [], [], [], [])
    assert "Stated preferences" not in out
    assert "Known bugs" not in out
    # Backward-compatible: old 4-positional-arg call sites still work.
    out2 = format_full_memory_context([], [], [], [])
    assert "Stated preferences" not in out2
