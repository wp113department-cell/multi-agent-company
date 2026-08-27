"""Tests for app.main._barot_temp_agent_ttl_loop — same "let asyncio.sleep
fire once then cancel" technique as test_benchmark_baseline_loop.py /
test_lesson_archive_loop.py."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.agents.temporary_agent import get_temporary_agent_pool
from app.fleet.capability_registry import get_capability_registry
from app.main import _barot_temp_agent_ttl_loop


def _run_loop_once() -> None:
    call_count = {"n": 0}

    async def _sleep_once_then_cancel(*args: object, **kwargs: object) -> None:
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise asyncio.CancelledError()

    async def _drive() -> None:
        with patch("asyncio.sleep", side_effect=_sleep_once_then_cancel):
            with pytest.raises(asyncio.CancelledError):
                await _barot_temp_agent_ttl_loop()

    asyncio.run(_drive())


def test_ttl_loop_disabled_when_interval_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "barot_agent_ttl_sweep_interval_seconds", 0)
    asyncio.run(_barot_temp_agent_ttl_loop())  # returns immediately, never sleeps


def test_ttl_loop_reaps_expired_temp_agent() -> None:
    pool = get_temporary_agent_pool()
    slot = pool.spawn(
        task_id="1",
        required_capability="td_ttl_loop_cap",
        task_description="task",
        briefing="briefing",
        tool_names=["read_file"],
        model="test-model",
        repo_path="/tmp",
    )
    assert slot is not None
    slot.ttl_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)

    try:
        _run_loop_once()
        assert get_capability_registry().get(slot.role_name) is None
    finally:
        pool.scrap(slot.role_name, reason="test_cleanup")


def test_ttl_loop_iteration_failure_does_not_crash_the_loop() -> None:
    """Mirrors every other loop's own try/except-and-log convention — a
    sweep_expired() exception must be logged and swallowed, not propagate
    and kill the loop task."""
    call_count = {"n": 0}

    async def _sleep_once_then_cancel(*args: object, **kwargs: object) -> None:
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise asyncio.CancelledError()

    async def _drive() -> None:
        with patch("asyncio.sleep", side_effect=_sleep_once_then_cancel), patch(
            "app.agents.temporary_agent.get_temporary_agent_pool",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _barot_temp_agent_ttl_loop()

    asyncio.run(_drive())  # must reach CancelledError, not propagate RuntimeError
