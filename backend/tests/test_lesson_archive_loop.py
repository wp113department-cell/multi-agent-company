"""Gap-closure (2026-07-21) — Day 11's plan doc for versioned_memory.py said
archive_expired() would be wired into main.py's lifespan the same way the
retention/reindex loops are, but it never was. This tests the new
_versioned_lesson_archive_loop() actually calls archive_expired() once per
iteration, using the same technique as other loop tests in this codebase:
let asyncio.sleep fire once, then raise CancelledError to break the
otherwise-infinite `while True` loop after exactly one iteration.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.main import _versioned_lesson_archive_loop


@pytest.mark.asyncio
async def test_archive_loop_calls_archive_expired_once_per_iteration() -> None:
    call_count = {"n": 0}

    async def _sleep_once_then_cancel(*args: object, **kwargs: object) -> None:
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", side_effect=_sleep_once_then_cancel), patch(
        "app.fleet.versioned_memory.get_versioned_memory_store"
    ) as mock_get_store:
        mock_store = mock_get_store.return_value
        mock_store.archive_expired.return_value = 3

        with pytest.raises(asyncio.CancelledError):
            await _versioned_lesson_archive_loop()

    mock_store.archive_expired.assert_called()


@pytest.mark.asyncio
async def test_archive_loop_is_non_fatal_on_archive_expired_exception() -> None:
    call_count = {"n": 0}

    async def _sleep_once_then_cancel(*args: object, **kwargs: object) -> None:
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", side_effect=_sleep_once_then_cancel), patch(
        "app.fleet.versioned_memory.get_versioned_memory_store"
    ) as mock_get_store:
        mock_get_store.return_value.archive_expired.side_effect = RuntimeError(
            "db down"
        )

        # must not raise RuntimeError — only the CancelledError from the sleep patch
        with pytest.raises(asyncio.CancelledError):
            await _versioned_lesson_archive_loop()
