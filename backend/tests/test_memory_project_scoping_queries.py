"""Gap-closure Day 3 (answers.md root-cause 1a, Q5/Q51/Q94/Q95/Q114/Q120) —
real-DB proof that repo_id-scoped querying actually isolates two real repos'
memories from each other, not just that the column exists (Day 2 covered
that). Mirrors test_versioned_memory.py's real-DB-not-mocked-DB-but-mocked-
embedding convention for this same table: `_embed` is patched (not the DB) so
results are driven by the real SQL WHERE clause under test, not blocked by
the zero-vector short-circuit that fires for both the write path AND the
query-text embedding when VOYAGE_API_KEY isn't set in this environment.

_embed is imported via a fresh `from app.memory.store import _embed` inside
every embed_*/query_* call, so patching app.memory.store._embed directly
(not a local re-export) is what actually takes effect — same reasoning
documented in test_versioned_memory.py and test_prompt_registry.py.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.models import MemoryEmbedding, Repo
from app.memory.store import (
    embed_failure,
    embed_task_outcome,
    query_failures,
    query_similar_tasks,
)


def _vector_for(text_to_embed: str) -> list[float]:
    """Deterministic, content-derived fake embedding — see
    test_memory_archived_filter.py's identical helper for the full
    rationale (Day 42's dedup guard is cosine-similarity-sensitive; a
    single shared constant vector would make distinct rows in the same
    category falsely collide as "duplicates")."""
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _make_repo(session: AsyncSession, suffix: str) -> int:
    repo = Repo(
        github_url=f"https://github.com/test/scoping-{suffix}",
        name=f"scoping-{suffix}",
        local_path=f"/tmp/scoping-{suffix}",
        status="ready",
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return int(repo.id)


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_project_a_scoped_memory_never_returned_by_project_bs_scoped_query(
    _mock_embed: object,
) -> None:
    """The exact acceptance criterion from the gap-closure plan: seed two
    real repos, write one task-outcome memory scoped to each, and prove a
    repo_id-filtered query for repo A never returns repo B's row."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_a = f"td-scope-a-{suffix}"
    task_b = f"td-scope-b-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = await _make_repo(session, f"a-{suffix}")
            repo_b = await _make_repo(session, f"b-{suffix}")

            await embed_task_outcome(
                task_id=task_a,
                description=f"unique marker alpha needle {suffix}",
                summary="project A summary",
                outcome="completed",
                files_changed=[],
                db=session,
                repo_id=repo_a,
            )
            await embed_task_outcome(
                task_id=task_b,
                description=f"unique marker bravo needle {suffix}",
                summary="project B summary",
                outcome="completed",
                files_changed=[],
                db=session,
                repo_id=repo_b,
            )

            # Query scoped to repo A must never surface repo B's row, and
            # vice versa — this is the real isolation guarantee, not just
            # that the column exists.
            results_for_a = await query_similar_tasks(
                "irrelevant query text", session, top_k=1000, repo_id=repo_a
            )
            task_ids_for_a = {r["task_id"] for r in results_for_a}
            assert task_a in task_ids_for_a
            assert task_b not in task_ids_for_a

            results_for_b = await query_similar_tasks(
                "irrelevant query text", session, top_k=1000, repo_id=repo_b
            )
            task_ids_for_b = {r["task_id"] for r in results_for_b}
            assert task_b in task_ids_for_b
            assert task_a not in task_ids_for_b

            # Unfiltered (repo_id=None, the pre-Day-3 default) must still see
            # both — this capability is additive, not a breaking change.
            results_unfiltered = await query_similar_tasks(
                "irrelevant query text", session, top_k=1000
            )
            task_ids_unfiltered = {r["task_id"] for r in results_unfiltered}
            assert task_a in task_ids_unfiltered
            assert task_b in task_ids_unfiltered

            await session.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id.in_([task_a, task_b])
                )
            )
            await session.execute(delete(Repo).where(Repo.id.in_([repo_a, repo_b])))
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_legacy_unscoped_row_stays_visible_to_every_scoped_query(
    _mock_embed: object,
) -> None:
    """A pre-Day-2-shaped row (repo_id=NULL, no repo_id passed at write time)
    is a deliberate exception: it must remain visible to every project's
    scoped query as general fallback knowledge, since there's no way to
    retroactively attribute it to one repo — this is documented, not a bug."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_legacy = f"td-legacy-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_id = await _make_repo(session, f"legacy-{suffix}")

            await embed_task_outcome(
                task_id=task_legacy,
                description=f"legacy unscoped marker {suffix}",
                summary="written with no repo_id, like every pre-migration row",
                outcome="completed",
                files_changed=[],
                db=session,
                # repo_id intentionally omitted — simulates a pre-Day-2 row.
            )

            results = await query_similar_tasks(
                "irrelevant query text", session, top_k=1000, repo_id=repo_id
            )
            task_ids = {r["task_id"] for r in results}
            assert task_legacy in task_ids, (
                "a legacy/unscoped row must still surface for a real, "
                "unrelated project's scoped query"
            )

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_legacy)
            )
            await session.execute(delete(Repo).where(Repo.id == repo_id))
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_failure_records_are_also_isolated_by_repo_id(
    _mock_embed: object,
) -> None:
    """query_failures shares the exact same filter pattern as
    query_similar_tasks — one representative second query_* function proves
    the pattern was applied consistently, not just to the first one."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_a = f"td-fail-a-{suffix}"
    task_b = f"td-fail-b-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = await _make_repo(session, f"fail-a-{suffix}")
            repo_b = await _make_repo(session, f"fail-b-{suffix}")

            await embed_failure(
                task_id=task_a,
                error_description=f"error in project A {suffix}",
                root_cause="root cause A",
                db=session,
                repo_id=repo_a,
            )
            await embed_failure(
                task_id=task_b,
                error_description=f"error in project B {suffix}",
                root_cause="root cause B",
                db=session,
                repo_id=repo_b,
            )

            results_for_a = await query_failures(
                "irrelevant", session, top_k=1000, repo_id=repo_a
            )
            task_ids_for_a = {r["task_id"] for r in results_for_a}
            assert task_a in task_ids_for_a
            assert task_b not in task_ids_for_a

            await session.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id.in_([task_a, task_b])
                )
            )
            await session.execute(delete(Repo).where(Repo.id.in_([repo_a, repo_b])))
            await session.commit()
    finally:
        await engine.dispose()
