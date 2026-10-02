"""Qoder cross-check MEM-03-002 (2026-10-02): with MEMORY_CONSOLIDATION_ENABLED
=false the loop `continue`d past the zero-vector repair, its only scheduled
caller, so broken (all-zero) memory embeddings were never repaired.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import app.main as main
from app.config import get_settings


def test_repair_runs_even_when_consolidation_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "memory_consolidation_enabled", False)
    calls: list[str] = []
    sleeps = {"n": 0}

    async def fake_sleep(_s: float) -> None:
        sleeps["n"] += 1
        if sleeps["n"] > 1:
            raise asyncio.CancelledError  # stop after one cycle

    async def fake_repair(_db: Any) -> int:
        calls.append("repair")
        return 0

    class _Session:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_a: Any) -> None:
            return None

    import app.db.session as session_mod
    import app.memory.store as store_mod

    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(store_mod, "reembed_zero_vector_rows", fake_repair)
    monkeypatch.setattr(session_mod, "get_async_session", lambda: _Session())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main._versioned_lesson_consolidation_loop())
    assert calls == ["repair"]
