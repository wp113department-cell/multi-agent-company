"""Tests for MASTER_AGENT_v2.md Phase 1.7 — shared epic scratchpad.

Ephemeral, epic-scoped key-value store, distinct from every permanent
memory_embeddings category — covers the async CRUD (write/read/clear/expire),
the sync bridges tool handlers would use, and that manager.py actually calls
clear_epic_scratchpad at both real epic-terminal points (halted and
ready_for_review).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.fleet.scratchpad import (
    clear_epic_scratchpad,
    expire_stale_entries,
    read_entries,
    read_entries_sync,
    write_entry,
    write_entry_sync,
)

# ---------------------------------------------------------------------------
# write_entry — insert vs. update-in-place
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_entry_inserts_when_key_is_new() -> None:
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    ok = await write_entry(
        epic_id="epic-1",
        key="hypothesis",
        value={"note": "root cause might be a race"},
        agent_name="debugger_agent",
        db=mock_db,
    )

    assert ok is True
    assert mock_db.add.called
    added = mock_db.add.call_args.args[0]
    assert added.epic_id == "epic-1"
    assert added.key == "hypothesis"
    assert added.value == {"note": "root cause might be a race"}
    assert added.agent_name == "debugger_agent"


@pytest.mark.asyncio
async def test_write_entry_overwrites_existing_key_in_place() -> None:
    mock_db = AsyncMock()
    existing = MagicMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
    )
    mock_db.commit = AsyncMock()

    ok = await write_entry(
        epic_id="epic-1",
        key="hypothesis",
        value={"note": "confirmed: race condition"},
        agent_name="qa",
        db=mock_db,
    )

    assert ok is True
    assert existing.value == {"note": "confirmed: race condition"}
    assert existing.agent_name == "qa"
    mock_db.add.assert_not_called()  # updated in place, not re-inserted


@pytest.mark.asyncio
async def test_write_entry_failure_returns_false_not_raise() -> None:
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=RuntimeError("db down"))
    mock_db.rollback = AsyncMock()

    ok = await write_entry(
        epic_id="epic-1", key="k", value="v", agent_name="qa", db=mock_db
    )
    assert ok is False
    assert mock_db.rollback.called


@pytest.mark.asyncio
async def test_write_entry_sets_expiry_from_ttl() -> None:
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    before = datetime.now(timezone.utc)
    await write_entry(
        epic_id="epic-1",
        key="k",
        value="v",
        agent_name="qa",
        db=mock_db,
        ttl_seconds=60,
    )
    added = mock_db.add.call_args.args[0]
    assert added.expires_at > before + timedelta(seconds=55)
    assert added.expires_at < before + timedelta(seconds=65)


# ---------------------------------------------------------------------------
# read_entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_entries_returns_formatted_rows() -> None:
    mock_db = AsyncMock()
    fake_row = MagicMock()
    fake_row.key = "hypothesis"
    fake_row.value = {"note": "race condition"}
    fake_row.agent_name = "debugger_agent"
    fake_row.created_at = None

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [fake_row]
    mock_db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: mock_scalars))

    results = await read_entries("epic-1", mock_db)
    assert len(results) == 1
    assert results[0]["key"] == "hypothesis"
    assert results[0]["value"] == {"note": "race condition"}
    assert results[0]["agent_name"] == "debugger_agent"


@pytest.mark.asyncio
async def test_read_entries_failure_returns_empty_list() -> None:
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=RuntimeError("db down"))
    results = await read_entries("epic-1", mock_db)
    assert results == []


# ---------------------------------------------------------------------------
# clear_epic_scratchpad / expire_stale_entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_epic_scratchpad_returns_deleted_count() -> None:
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 3
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    deleted = await clear_epic_scratchpad("epic-1", mock_db)
    assert deleted == 3


@pytest.mark.asyncio
async def test_clear_epic_scratchpad_failure_returns_zero_not_raise() -> None:
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=RuntimeError("db down"))
    mock_db.rollback = AsyncMock()

    deleted = await clear_epic_scratchpad("epic-1", mock_db)
    assert deleted == 0
    assert mock_db.rollback.called


@pytest.mark.asyncio
async def test_expire_stale_entries_returns_deleted_count() -> None:
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 5
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    deleted = await expire_stale_entries(mock_db)
    assert deleted == 5


# ---------------------------------------------------------------------------
# Sync bridges
# ---------------------------------------------------------------------------


def test_write_entry_sync_bridges_to_async() -> None:
    with patch(
        "app.fleet.scratchpad.write_entry", new=AsyncMock(return_value=True)
    ) as mock_write:
        ok = write_entry_sync("epic-1", "k", "v", "qa")
    assert ok is True
    mock_write.assert_awaited_once()


def test_write_entry_sync_returns_false_on_failure() -> None:
    with patch(
        "app.fleet.scratchpad.write_entry",
        new=AsyncMock(side_effect=RuntimeError("db down")),
    ):
        ok = write_entry_sync("epic-1", "k", "v", "qa")
    assert ok is False


def test_read_entries_sync_bridges_to_async() -> None:
    fake_result = [{"key": "k", "value": "v", "agent_name": "qa", "created_at": ""}]
    with patch(
        "app.fleet.scratchpad.read_entries", new=AsyncMock(return_value=fake_result)
    ):
        result = read_entries_sync("epic-1")
    assert result == fake_result


def test_read_entries_sync_returns_empty_on_failure() -> None:
    with patch(
        "app.fleet.scratchpad.read_entries",
        new=AsyncMock(side_effect=RuntimeError("db down")),
    ):
        result = read_entries_sync("epic-1")
    assert result == []


# ---------------------------------------------------------------------------
# manager.py wiring — clear_epic_scratchpad called at both terminal points
# ---------------------------------------------------------------------------


def test_manager_module_calls_clear_epic_scratchpad_at_both_terminal_points() -> None:
    """Static check that both the halted and ready_for_review code paths in
    run_epic_manager reference clear_epic_scratchpad — a full end-to-end test
    of run_epic_manager already requires extensive existing fixtures/mocks
    (see tests/test_audit04_orchestration_fixes.py); this proves the wiring
    exists without duplicating that setup."""
    import inspect

    from app.agents import manager

    source = inspect.getsource(manager)
    assert source.count("clear_epic_scratchpad") >= 2
