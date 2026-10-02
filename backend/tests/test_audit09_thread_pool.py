"""Production audit 09 (2026-10-02): the default thread pool fits the fleet.

Agent runs execute via asyncio.to_thread(). The stdlib default pool is
min(32, cpu_count + 4) threads, so on a 6-core host only 10 of the configured
20 concurrent agent runs could execute, and every short to_thread call queued
behind them. Startup now sizes the pool from MAX_CONCURRENT_AGENT_RUNS.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from app.config import get_settings
from app.main import _size_default_executor


def test_pool_has_room_for_every_agent_run_plus_short_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "max_concurrent_agent_runs", 20)

    async def _probe() -> int:
        _size_default_executor()
        release = threading.Event()
        # Occupy one worker per configured agent run, as long agent runs do.
        blockers = [asyncio.to_thread(release.wait, 10) for _ in range(20)]
        tasks = [asyncio.ensure_future(b) for b in blockers]
        await asyncio.sleep(0.05)
        try:
            # A short call must still get a thread immediately.
            return await asyncio.wait_for(asyncio.to_thread(lambda: 42), timeout=2)
        finally:
            release.set()
            await asyncio.gather(*tasks)

    assert asyncio.run(_probe()) == 42
