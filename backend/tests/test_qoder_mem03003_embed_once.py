"""Qoder cross-check MEM-03-003 (2026-10-02): each agent run embedded the same
description 7 times (one Voyage round-trip per memory category). Identical
(model, text) now reuses the recent embedding; failures are never cached.
A fake voyageai module counts calls — no network, no spend.
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest

import app.memory.store as store
from app.config import get_settings


@pytest.fixture()
def fake_voyage(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"n": 0, "fail": 0}

    class Client:
        def __init__(self, api_key: str) -> None:
            pass

        def embed(self, texts: list[str], model: str, input_type: str) -> Any:
            calls["n"] += 1
            if calls["fail"]:
                calls["fail"] -= 1
                raise RuntimeError("provider down")
            return types.SimpleNamespace(embeddings=[[0.1] * 1536])

    monkeypatch.setitem(sys.modules, "voyageai", types.SimpleNamespace(Client=Client))
    monkeypatch.setattr(get_settings(), "voyage_api_key", "test-key")
    monkeypatch.setattr(store, "_EMBED_BACKOFF_SECONDS", 0.0)
    store._EMBED_MEMO.clear()
    yield calls
    store._EMBED_MEMO.clear()


def test_same_text_is_embedded_once(fake_voyage: dict[str, int]) -> None:
    async def run() -> None:
        for _ in range(7):
            assert (await store._embed("same description"))[0] == 0.1
        await store._embed("a different description")

    asyncio.run(run())
    assert fake_voyage["n"] == 2


def test_failures_are_not_cached(fake_voyage: dict[str, int]) -> None:
    fake_voyage["fail"] = store._EMBED_ATTEMPTS  # every attempt of the first call fails

    async def run() -> tuple[list[float], list[float]]:
        first = await store._embed("flaky")
        second = await store._embed("flaky")
        return first, second

    first, second = asyncio.run(run())
    assert first == store._ZERO_VECTOR_1536
    assert second[0] == 0.1, "a failure was cached instead of retried"
