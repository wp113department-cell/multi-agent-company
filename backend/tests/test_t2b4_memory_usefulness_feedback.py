"""T2-B4 (2026-09-22, GRIDIRON_PARTIAL #98 "Memory Quality Control
(accuracy validation)").

Before this, the composite memory ranking score only ever blended
similarity/recency/reuse_count/importance/verified — none of which measure
whether retrieving and using a specific memory actually HELPED a later
agent (`verified` is a write-time outcome boolean; the separate
MemoryQualityDecision gate is a write-time authorship-quality check).
This adds a real explicit usage-feedback signal (helpful_count/
not_helpful_count), a POST /api/memory/{id}/feedback endpoint, and a new
composite-score term for it — neutral (0.5 contribution) until a memory has
actually been rated at least once, real thereafter.

Matches tests/test_gap41_composite_scoring.py's own real-DB convention.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import MemoryEmbedding
from app.main import app
from app.memory.store import embed_task_outcome, query_similar_tasks


def _vector_for(text_to_embed: str) -> list[float]:
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _make_memory_row(task_id: str, marker: str) -> int:
    engine = _engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            with patch("app.memory.store._embed", side_effect=_vector_for):
                await embed_task_outcome(
                    task_id=task_id,
                    description=marker,
                    summary="s",
                    outcome="completed",
                    files_changed=[],
                    db=session,
                )
            from sqlalchemy import select

            result = await session.execute(
                select(MemoryEmbedding.id).where(MemoryEmbedding.task_id == task_id)
            )
            return result.scalar_one()
    finally:
        await engine.dispose()


def _cleanup(task_id: str) -> None:
    async def _run() -> None:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_feedback_endpoint_persists_and_returns_404_for_unknown_id() -> None:
    task_id = f"td-t2b4-feedback-{uuid.uuid4().hex[:8]}"
    marker = f"usefulness feedback marker {task_id}"
    memory_id = asyncio.run(_make_memory_row(task_id, marker))
    try:
        with TestClient(app) as client:
            resp = client.post(f"/api/memory/{memory_id}/feedback", json={"helpful": True})
            assert resp.status_code == 200, resp.text
            assert resp.json() == {"ok": True, "id": memory_id, "helpful": True}

            resp2 = client.post("/api/memory/999999999/feedback", json={"helpful": False})
            assert resp2.status_code == 404
    finally:
        _cleanup(task_id)


def test_feedback_route_is_authenticated_only_not_approver_only() -> None:
    from fastapi.routing import APIRoute

    def dependency_names(route: APIRoute, inherited: tuple) -> set[str]:
        names: set[str] = set()

        def walk(d: object) -> None:
            for sub in d.dependencies:  # type: ignore[attr-defined]
                if sub.call is not None:
                    names.add(getattr(sub.call, "__name__", ""))
                walk(sub)

        walk(route.dependant)
        for dep in inherited:
            names.add(getattr(getattr(dep, "dependency", dep), "__name__", ""))
        return names

    found: list[tuple[str, str, set[str]]] = []

    def collect(router: object, prefix: str = "", inherited: tuple = ()) -> None:
        for r in router.routes:  # type: ignore[attr-defined]
            if type(r).__name__ == "_IncludedRouter":
                ctx = r.include_context
                collect(
                    r.original_router,
                    prefix + (getattr(ctx, "prefix", "") or ""),
                    inherited + tuple(getattr(ctx, "dependencies", None) or ()),
                )
            elif isinstance(r, APIRoute):
                for method in r.methods - {"HEAD", "OPTIONS"}:
                    found.append((method, prefix + r.path, dependency_names(r, inherited)))

    collect(app)
    matches = [f for f in found if f[0] == "POST" and f[1] == "/api/memory/{memory_id}/feedback"]
    assert len(matches) == 1
    _, _, deps = matches[0]
    assert "require_authenticated" in deps
    assert "require_approver" not in deps


@pytest.mark.asyncio
async def test_positive_feedback_increases_composite_score_ranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real behavioral proof: two rows with identical similarity/
    recency/reuse/importance/verified (same content, same write) must NOT
    tie once one of them has real positive usefulness feedback and the
    other doesn't — mirrors test_gap41_composite_scoring.py's own
    'identical similarity, differing signal' proof shape for reuse/
    importance, including its exact MEMORY_DEDUP_ENABLED=false pattern
    (writing identical content twice needs dedup off to get two genuinely
    distinct rows)."""
    from app.config import reset_settings_cache
    from app.memory.store import record_memory_feedback

    monkeypatch.setenv("MEMORY_DEDUP_ENABLED", "false")
    reset_settings_cache()
    try:
        engine = _engine()
        suffix = uuid.uuid4().hex[:8]
        task_id_helped = f"td-t2b4-helped-{suffix}"
        task_id_control = f"td-t2b4-control-{suffix}"
        marker = f"usefulness ranking proof marker {suffix}"
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                with patch("app.memory.store._embed", side_effect=_vector_for):
                    row_helped = await embed_task_outcome(
                        task_id=task_id_helped,
                        description=marker,
                        summary="s",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                    )
                    row_control = await embed_task_outcome(
                        task_id=task_id_control,
                        description=marker,
                        summary="s",
                        outcome="completed",
                        files_changed=[],
                        db=session,
                    )
                    assert row_helped is not None and row_control is not None
                    assert row_helped.id != row_control.id  # dedup genuinely off

                    for _ in range(3):
                        assert await record_memory_feedback(row_helped.id, True, session)

                    results = await query_similar_tasks(marker, session, top_k=1000)
                helped = next(r for r in results if r["task_id"] == task_id_helped)
                control = next(r for r in results if r["task_id"] == task_id_control)
                assert helped["similarity"] == pytest.approx(
                    control["similarity"], abs=1e-6
                )
                assert helped["composite_score"] > control["composite_score"]

                await session.execute(
                    delete(MemoryEmbedding).where(
                        MemoryEmbedding.task_id.in_([task_id_helped, task_id_control])
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()
    finally:
        reset_settings_cache()
