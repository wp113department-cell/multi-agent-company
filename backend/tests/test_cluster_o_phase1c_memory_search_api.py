"""Stage 4 Cluster O Phase 1c (2026-08-05) — GET /api/memory/search gained an
explicit, optional `repo_id` query param (CLUSTER_O_DESIGN.md change point H).
Deliberately explicit, not auto-injected (§2 Q2): a human debugging memory
should choose what they're searching, not have it silently narrowed — so
this phase adds exactly one query parameter, nothing else.

Two layers of verification, deliberately not just one:

1. Most tests call search_memory() directly (matching this suite's own
   established convention for FastAPI endpoint functions, e.g.
   test_memory_hooks.py's run_specialized_agent_sync(...) calls) — proves
   the function body's own logic against 2 real repositories plus global
   memory.
2. test_search_memory_real_http_request_isolates_two_real_repos below goes
   through a REAL TestClient HTTP GET request against the actual mounted
   route (same pattern as test_phase62_reporting_endpoints.py's own
   _client()/dependency_overrides[get_db] convention) — this is the piece a
   direct function call cannot prove: that FastAPI's own Query()
   ?repo_id=<int> parsing on a real request actually resolves to a real int
   (not the Query() sentinel object direct calls see — confirmed live while
   writing this suite: omitting repo_id in a *direct* call yields the
   literal, unresolved Query(None) object, not a plain None, since that
   resolution only happens inside real FastAPI request handling). Required
   before Phase 1d can proceed, per the explicit "only if the API layer is
   fully verified end-to-end" instruction.

Verifies, against 2 real repositories plus global memory (real Postgres, no
mocked DB):
  1. repo_id=A returns A's own rows + the global/legacy row, never B's
  2. repo_id=B returns B's own rows + the global/legacy row, never A's
  3. omitting repo_id (the default) searches fully unscoped — exactly the
     pre-Phase-1c behavior, proving backward compatibility
  4. the same isolation holds through a real HTTP request, not just a
     direct Python call
"""

from __future__ import annotations

import hashlib
import random
import uuid
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.memory import router, search_memory
from app.config import get_settings
from app.db.models import MemoryEmbedding, Repo
from app.db.session import get_db
from app.memory.store import embed_task_outcome


def _vector_for(text_to_embed: str) -> list[float]:
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _make_repo(session: AsyncSession, suffix: str) -> int:
    repo = Repo(
        github_url=f"https://github.com/test/clustero-1c-{suffix}",
        name=f"clustero-1c-{suffix}",
        local_path=f"/tmp/clustero-1c-{suffix}",
        status="ready",
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return int(repo.id)


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_search_memory_api_isolates_two_real_repos_plus_global(
    _mock_embed: object,
) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_a = f"td-1c-a-{suffix}"
    task_b = f"td-1c-b-{suffix}"
    task_legacy = f"td-1c-legacy-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = await _make_repo(session, f"a-{suffix}")
            repo_b = await _make_repo(session, f"b-{suffix}")

            await embed_task_outcome(
                task_id=task_a,
                description=f"1c marker A {suffix}",
                summary="A",
                outcome="completed",
                files_changed=[],
                db=session,
                repo_id=repo_a,
            )
            await embed_task_outcome(
                task_id=task_b,
                description=f"1c marker B {suffix}",
                summary="B",
                outcome="completed",
                files_changed=[],
                db=session,
                repo_id=repo_b,
            )
            await embed_task_outcome(
                task_id=task_legacy,
                description=f"1c marker legacy {suffix}",
                summary="legacy",
                outcome="completed",
                files_changed=[],
                db=session,
                # repo_id intentionally omitted — global/legacy row
            )

            # 1. repo_id=A: sees A + global, never B
            results_a = await search_memory(
                q="irrelevant", top_k=20, repo_id=repo_a, db=session
            )
            ids_a = {r["task_id"] for r in results_a}
            assert task_a in ids_a
            assert task_legacy in ids_a
            assert task_b not in ids_a

            # 2. repo_id=B: sees B + global, never A
            results_b = await search_memory(
                q="irrelevant", top_k=20, repo_id=repo_b, db=session
            )
            ids_b = {r["task_id"] for r in results_b}
            assert task_b in ids_b
            assert task_legacy in ids_b
            assert task_a not in ids_b

            await session.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id.in_([task_a, task_b, task_legacy])
                )
            )
            await session.execute(delete(Repo).where(Repo.id.in_([repo_a, repo_b])))
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_search_memory_api_omitted_repo_id_stays_fully_unscoped() -> None:
    """Backward compatibility, verified at the wiring level rather than by
    re-proving composite-score ranking against this shared test DB's own
    accumulated rows (which would be ranking-dependent and flaky, not a
    property of what Phase 1c actually changed). query_similar_tasks is
    mocked here specifically to inspect the repo_id value that actually
    reaches it — the real SQL-level "repo_id=None means unscoped" guarantee
    is already proven by test_memory_project_scoping_queries.py (Day 3) and
    is not re-tested here.

    repo_id=None is passed explicitly rather than omitted: a direct Python
    call bypasses FastAPI's own Query()-default-resolution machinery
    entirely (confirmed live — omitting it here yields the literal
    `Query(None)` sentinel object as the value, not a resolved `None`,
    since that resolution only happens inside real FastAPI request
    handling). What this test verifies is that search_memory's own body
    correctly forwards repo_id=None to query_similar_tasks — exactly the
    value FastAPI's real DI layer already produces for an omitted query
    param in production, which is a well-tested third-party concern, not
    something Cluster O needs to re-verify."""
    from unittest.mock import AsyncMock

    mock_db = AsyncMock()
    with patch(
        "app.api.memory.query_similar_tasks", new=AsyncMock(return_value=[])
    ) as mock_query:
        await search_memory(q="anything", top_k=5, repo_id=None, db=mock_db)

    mock_query.assert_awaited_once()
    assert mock_query.await_args is not None
    assert mock_query.await_args.kwargs["repo_id"] is None


def _new_isolated_db_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _http_client() -> TestClient:
    """Same pattern as test_phase62_reporting_endpoints.py's own _client():
    a minimal FastAPI app mounting only this router, with get_db overridden
    to a real isolated DB session — a genuine HTTP request through FastAPI's
    own routing/query-parsing layer, not a direct Python call."""

    app = FastAPI()
    app.include_router(router)

    async def _override() -> Any:
        engine = _new_isolated_db_engine()
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
        await engine.dispose()

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def test_search_memory_real_http_request_isolates_two_real_repos() -> None:
    """The layer direct-call tests above cannot prove: a genuine HTTP GET
    with a real ?repo_id=<int> query string, parsed by FastAPI's own
    Query() machinery, against a real running route — closing exactly the
    gap found while writing this suite (a direct call sees the unresolved
    Query() sentinel, not a real int/None)."""
    import asyncio

    suffix = uuid.uuid4().hex[:8]
    task_a = f"td-1c-http-a-{suffix}"
    task_b = f"td-1c-http-b-{suffix}"

    async def _seed() -> tuple[int, int]:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                with patch("app.memory.store._embed", side_effect=_vector_for):
                    repo_a = await _make_repo(session, f"http-a-{suffix}")
                    repo_b = await _make_repo(session, f"http-b-{suffix}")
                    await embed_task_outcome(
                        task_id=task_a,
                        description=f"1c http marker A {suffix}",
                        summary="A",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                        repo_id=repo_a,
                    )
                    await embed_task_outcome(
                        task_id=task_b,
                        description=f"1c http marker B {suffix}",
                        summary="B",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                        repo_id=repo_b,
                    )
                return repo_a, repo_b
        finally:
            await engine.dispose()

    async def _cleanup(repo_a: int, repo_b: int) -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(MemoryEmbedding).where(
                        MemoryEmbedding.task_id.in_([task_a, task_b])
                    )
                )
                await session.execute(delete(Repo).where(Repo.id.in_([repo_a, repo_b])))
                await session.commit()
        finally:
            await engine.dispose()

    repo_a, repo_b = asyncio.run(_seed())
    try:
        with patch("app.memory.store._embed", side_effect=_vector_for):
            with _http_client() as client:
                resp_a = client.get(
                    "/api/memory/search",
                    params={"q": "irrelevant", "top_k": 20, "repo_id": repo_a},
                )
                resp_b = client.get(
                    "/api/memory/search",
                    params={"q": "irrelevant", "top_k": 20, "repo_id": repo_b},
                )

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        ids_a = {r["task_id"] for r in resp_a.json()}
        ids_b = {r["task_id"] for r in resp_b.json()}

        assert task_a in ids_a
        assert task_b not in ids_a
        assert task_b in ids_b
        assert task_a not in ids_b
    finally:
        asyncio.run(_cleanup(repo_a, repo_b))
