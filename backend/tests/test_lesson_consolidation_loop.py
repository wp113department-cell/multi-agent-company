"""plan14 Day 3 Task 5 (Memory Consolidation) — app/main.py's
_versioned_lesson_consolidation_loop, mirroring the exact same pattern
test_lesson_archive_loop.py already established for
_versioned_lesson_archive_loop: let asyncio.sleep fire once, then raise
CancelledError to break the otherwise-infinite `while True` loop after
exactly one iteration.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.main import _versioned_lesson_consolidation_loop


@pytest.mark.asyncio
async def test_consolidation_loop_calls_consolidate_once_per_iteration() -> None:
    call_count = {"n": 0}

    async def _sleep_once_then_cancel(*args: object, **kwargs: object) -> None:
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise asyncio.CancelledError()

    with (
        patch("asyncio.sleep", side_effect=_sleep_once_then_cancel),
        patch("app.config.get_settings") as mock_settings,
        patch(
            "app.fleet.versioned_memory.get_versioned_memory_store"
        ) as mock_get_store,
    ):
        mock_settings.return_value.memory_consolidation_enabled = True
        mock_settings.return_value.memory_consolidation_interval_hours = 24.0
        mock_store = mock_get_store.return_value
        mock_store.consolidate_published_lessons.return_value = []

        with pytest.raises(asyncio.CancelledError):
            await _versioned_lesson_consolidation_loop()

    mock_store.consolidate_published_lessons.assert_called()


@pytest.mark.asyncio
async def test_consolidation_loop_is_non_fatal_on_exception() -> None:
    call_count = {"n": 0}

    async def _sleep_once_then_cancel(*args: object, **kwargs: object) -> None:
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise asyncio.CancelledError()

    with (
        patch("asyncio.sleep", side_effect=_sleep_once_then_cancel),
        patch("app.config.get_settings") as mock_settings,
        patch(
            "app.fleet.versioned_memory.get_versioned_memory_store"
        ) as mock_get_store,
    ):
        mock_settings.return_value.memory_consolidation_enabled = True
        mock_settings.return_value.memory_consolidation_interval_hours = 24.0
        mock_get_store.return_value.consolidate_published_lessons.side_effect = (
            RuntimeError("db down")
        )

        # must not raise RuntimeError — only the CancelledError from the sleep patch
        with pytest.raises(asyncio.CancelledError):
            await _versioned_lesson_consolidation_loop()


@pytest.mark.asyncio
async def test_consolidation_loop_skips_call_when_disabled() -> None:
    call_count = {"n": 0}

    async def _sleep_once_then_cancel(*args: object, **kwargs: object) -> None:
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise asyncio.CancelledError()

    with (
        patch("asyncio.sleep", side_effect=_sleep_once_then_cancel),
        patch("app.config.get_settings") as mock_settings,
        patch(
            "app.fleet.versioned_memory.get_versioned_memory_store"
        ) as mock_get_store,
    ):
        mock_settings.return_value.memory_consolidation_enabled = False
        mock_settings.return_value.memory_consolidation_interval_hours = 24.0

        with pytest.raises(asyncio.CancelledError):
            await _versioned_lesson_consolidation_loop()

    mock_get_store.return_value.consolidate_published_lessons.assert_not_called()
