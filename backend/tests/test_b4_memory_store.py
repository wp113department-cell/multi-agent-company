"""Verification batch B4 (#73-#86, #87, #91-#97, #412) — the pgvector engineering memory,
on REAL Postgres with a deterministic hashed bag-of-words embedder (no API spend).

Defects proven before the fix:
* `_embed` called the SYNCHRONOUS Voyage client inside a coroutine, blocking the whole
  event loop for every API call;
* one transient provider failure produced a ZERO vector that was stored as if it were a
  memory — permanently unsearchable and never re-embedded.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import sys
import time
import types
import uuid

import pytest
from sqlalchemy import delete, select, text

from app.config import get_settings
from app.db.models import MemoryEmbedding, Repo
from app.db.session import get_async_session
from app.memory import store

DIM = 1536
TAG = "b4probe"
REAL_EMBED = store._embed  # captured BEFORE the autouse fixture swaps in the fake


def fake_embed_vec(s: str) -> list[float]:
    v = [0.0] * DIM
    for tok in {t.lower().strip(".,:;()") for t in s.split() if len(t) > 2}:
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        v[h % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


async def _fake_embed(s: str) -> list[float]:
    return fake_embed_vec(s)


@pytest.fixture(autouse=True)
def _embedder(monkeypatch):
    monkeypatch.setattr(store, "_embed", _fake_embed)
    monkeypatch.setattr(get_settings(), "memory_enabled", True)


@pytest.fixture
async def repos():
    async with get_async_session() as db:
        a, b = Repo(
            github_url=f"https://x/{TAG}-a-{uuid.uuid4().hex[:6]}",
            name="a",
            local_path="/tmp/a",
            status="ready",
        ), Repo(
            github_url=f"https://x/{TAG}-b-{uuid.uuid4().hex[:6]}",
            name="b",
            local_path="/tmp/b",
            status="ready",
        )
        db.add_all([a, b])
        await db.commit()
        await db.refresh(a), await db.refresh(b)
        ids = (a.id, b.id)
    yield ids
    async with get_async_session() as db:
        await db.execute(
            delete(MemoryEmbedding).where(MemoryEmbedding.task_id.like(f"{TAG}%"))
        )
        await db.execute(delete(Repo).where(Repo.id.in_(ids)))
        await db.commit()


async def _write(
    tid,
    desc,
    summary="completed the change carefully with tests",
    repo=None,
    outcome="completed",
):
    async with get_async_session() as db:
        return await store.embed_task_outcome(
            f"{TAG}-{tid}", desc, summary, outcome, ["a.py"], db, repo_id=repo
        )


async def _query(desc, repo=None, k=5):
    async with get_async_session() as db:
        return await store.query_similar_tasks(desc, db, top_k=k, repo_id=repo)


async def test_roundtrip_and_targeted_top_k(repos) -> None:
    a, _ = repos
    topics = [
        "postgres migration alembic revision",
        "react component tailwind styling",
        "docker compose networking bridge",
        "oauth jwt token refresh",
        "pytest fixture parametrize markers",
        "redis queue worker retry",
    ]
    for i, t in enumerate(topics):
        assert await _write(f"rt{i}", f"{t} task number {i} implementation", repo=a)
    res = await _query("postgres alembic migration revision", repo=a, k=3)
    assert 1 <= len(res) <= 3, "retrieval must be top-k, not a dump of the store"
    assert (
        "postgres" in res[0]["description"]
        and res[0]["similarity"] >= res[-1]["similarity"]
    )
    assert {
        "task_id",
        "outcome",
        "description",
        "summary",
        "files_changed",
        "similarity",
    } <= set(res[0])


async def test_project_memory_is_isolated_per_repo(repos) -> None:
    a, b = repos
    await _write(
        "iso-a", "kubernetes helm chart deployment values secrets rotation", repo=a
    )
    await _write(
        "iso-b",
        "kubernetes helm chart deployment values secrets rotation for other tenant",
        repo=b,
    )
    await _write(
        "iso-legacy",
        "kubernetes helm chart deployment legacy unscoped knowledge",
        repo=None,
    )
    in_a = {
        r["task_id"]
        for r in await _query("kubernetes helm chart deployment values", repo=a)
    }
    in_b = {
        r["task_id"]
        for r in await _query("kubernetes helm chart deployment values", repo=b)
    }
    assert f"{TAG}-iso-a" in in_a and f"{TAG}-iso-b" not in in_a
    assert f"{TAG}-iso-b" in in_b and f"{TAG}-iso-a" not in in_b
    assert (
        f"{TAG}-iso-legacy" in in_a and f"{TAG}-iso-legacy" in in_b
    )  # unscoped = shared fallback


async def test_near_duplicate_is_reused_not_reinserted(repos) -> None:
    a, _ = repos
    first = await _write(
        "dup1",
        "implement rate limiting middleware with sliding window counters",
        repo=a,
    )
    second = await _write(
        "dup2",
        "implement rate limiting middleware with sliding window counters",
        repo=a,
    )
    assert first.id == second.id
    async with get_async_session() as db:
        n = (
            (
                await db.execute(
                    select(MemoryEmbedding).where(
                        MemoryEmbedding.task_id.like(f"{TAG}-dup%")
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(n) == 1


async def test_concurrent_identical_writes_race_safely(repos) -> None:
    a, _ = repos
    rows = await asyncio.gather(
        *[
            _write(
                f"race{i}", "add websocket heartbeat reconnect backoff handling", repo=a
            )
            for i in range(8)
        ]
    )
    assert all(r is not None for r in rows)
    async with get_async_session() as db:
        n = (
            (
                await db.execute(
                    select(MemoryEmbedding).where(
                        MemoryEmbedding.task_id.like(f"{TAG}-race%")
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(n) == 1, f"advisory lock failed: {len(n)} duplicate rows"


async def test_quality_gate_rejects_placeholders_and_drafts_thin_content(repos) -> None:
    a, _ = repos
    assert await _write("q1", "ok", summary="done", repo=a) is None
    thin = await _write("q2", "tabs", summary="use tabs", repo=a)
    if thin is not None:
        assert thin.verified is False
    good = await _write(
        "q3", "refactor authentication middleware to use dependency injection", repo=a
    )
    assert good is not None and good.verified is True


async def test_archived_rows_never_surface(repos) -> None:
    a, _ = repos
    row = await _write(
        "arch1", "migrate legacy cron scripts into scheduled workers", repo=a
    )
    assert any(
        r["task_id"] == row.task_id
        for r in await _query("migrate legacy cron scripts scheduled workers", repo=a)
    )
    async with get_async_session() as db:
        await db.execute(
            text("update memory_embeddings set archived = true where id = :i"),
            {"i": row.id},
        )
        await db.commit()
    assert all(
        r["task_id"] != row.task_id
        for r in await _query("migrate legacy cron scripts scheduled workers", repo=a)
    )


async def test_memory_survives_a_process_restart(repos) -> None:
    """State lives in Postgres, not process memory: drop the engine and read again."""
    a, _ = repos
    await _write(
        "persist1", "introduce structured logging with correlation identifiers", repo=a
    )
    import app.db.session as sess

    sess._engine = None  # what a fresh process starts with
    sess._session_factory = None
    res = await _query("structured logging correlation identifiers", repo=a)
    assert any(r["task_id"] == f"{TAG}-persist1" for r in res)


# ------------------------------- the outage bug ---------------------------


async def test_zero_vector_rows_are_repaired_once_the_provider_is_back(
    repos, monkeypatch
) -> None:
    a, _ = repos

    async def down(_s: str) -> list[float]:
        return store._ZERO_VECTOR_1536

    monkeypatch.setattr(store, "_embed", down)
    row = await _write(
        "dead1", "configure nginx reverse proxy caching headers gzip", repo=a
    )
    assert row is not None  # stored... but dead
    monkeypatch.setattr(store, "_embed", _fake_embed)
    assert not any(
        r["task_id"] == row.task_id
        for r in await _query("nginx reverse proxy caching headers gzip", repo=a)
    )

    monkeypatch.setattr(get_settings(), "voyage_api_key", "test-key")
    async with get_async_session() as db:
        assert await store.reembed_zero_vector_rows(db, only_ids=[row.id]) == 1
    res = await _query("nginx reverse proxy caching headers gzip", repo=a)
    assert any(
        r["task_id"] == row.task_id for r in res
    ), "repaired row is still unsearchable"


async def test_repair_is_a_no_op_without_a_key_and_stops_while_the_provider_is_down(
    repos, monkeypatch
) -> None:
    a, _ = repos
    monkeypatch.setattr(get_settings(), "voyage_api_key", "")
    async with get_async_session() as db:
        assert await store.reembed_zero_vector_rows(db) == 0

    async def down(_s: str) -> list[float]:
        return store._ZERO_VECTOR_1536

    monkeypatch.setattr(store, "_embed", down)
    await _write(
        "dead2", "tune postgres autovacuum thresholds for large tables", repo=a
    )
    monkeypatch.setattr(get_settings(), "voyage_api_key", "test-key")
    async with get_async_session() as db:
        assert (
            await store.reembed_zero_vector_rows(db) == 0
        )  # provider still down: nothing "repaired"


def _fake_voyage(fail_times: int, delay: float = 0.0):
    calls = {"n": 0}

    class Client:
        def __init__(self, api_key=None): ...

        def embed(self, texts, model, input_type):
            calls["n"] += 1
            if delay:
                time.sleep(delay)  # a blocking network call
            if calls["n"] <= fail_times:
                raise RuntimeError("429 rate limited")
            return types.SimpleNamespace(embeddings=[[0.5] * DIM])

    mod = types.ModuleType("voyageai")
    mod.Client = Client  # type: ignore[attr-defined]
    return mod, calls


async def test_embed_retries_transient_failures(monkeypatch) -> None:
    mod, calls = _fake_voyage(fail_times=2)
    monkeypatch.setitem(sys.modules, "voyageai", mod)
    monkeypatch.setattr(store, "_EMBED_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(get_settings(), "voyage_api_key", "k")
    vec = await REAL_EMBED("hello world")
    assert vec[0] == 0.5 and calls["n"] == 3


async def test_embed_gives_up_after_the_attempt_budget(monkeypatch) -> None:
    mod, calls = _fake_voyage(fail_times=99)
    monkeypatch.setitem(sys.modules, "voyageai", mod)
    monkeypatch.setattr(store, "_EMBED_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(get_settings(), "voyage_api_key", "k")
    assert (
        await REAL_EMBED("x") == store._ZERO_VECTOR_1536
        and calls["n"] == store._EMBED_ATTEMPTS
    )


async def test_embed_without_a_key_is_the_zero_vector(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "voyage_api_key", "")
    assert await REAL_EMBED("x") == store._ZERO_VECTOR_1536


async def test_embed_does_not_block_the_event_loop(monkeypatch) -> None:
    mod, _ = _fake_voyage(fail_times=0, delay=0.4)
    monkeypatch.setitem(sys.modules, "voyageai", mod)
    monkeypatch.setattr(get_settings(), "voyage_api_key", "k")
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    t = asyncio.create_task(ticker())
    await REAL_EMBED("slow provider call")
    t.cancel()
    assert (
        ticks >= 8
    ), f"the event loop was blocked during the embed call (ticks={ticks})"
