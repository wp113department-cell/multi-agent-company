"""Gap-closure Day 7 (answers.md Q120) — real-DB proof that an archived
memory_embeddings row (archived=true, written by app/services/retention.py's
_archive_table() past MEMORY_EMBEDDINGS_RETENTION_DAYS) is actually excluded
from every query_* function, not just carrying a flag nothing reads. Before
this, the flag was write-only: retention marked rows archived but every
query still returned them forever, making the policy purely cosmetic.

Mirrors test_memory_project_scoping_queries.py's real-DB-with-mocked-
embedding convention for this table.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.models import MemoryEmbedding
from app.memory.store import (
    embed_architecture_note,
    embed_failure,
    embed_learning_signal,
    embed_procedure,
    embed_task_outcome,
    query_architecture_notes,
    query_failures,
    query_learning_signals,
    query_procedures,
    query_similar_tasks,
)
from app.services.retention import _archive_table


def _vector_for(text_to_embed: str) -> list[float]:
    """Deterministic, content-derived fake embedding — distinct text
    produces an effectively-orthogonal distinct vector (real embedding
    behavior), same text always reproduces the same vector. Gap-closure
    Day 42's dedup guard is cosine-similarity-sensitive; a single shared
    constant vector (this file's pre-Day-42 convention) would make every
    embed_*() call in the same category collide as a false "duplicate."
    """
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _mark_archived(session: AsyncSession, task_id: str) -> None:
    await session.execute(
        text(
            "UPDATE memory_embeddings SET archived = true, archived_at = now() "
            "WHERE task_id = :task_id"
        ),
        {"task_id": task_id},
    )
    await session.commit()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_query_similar_tasks_excludes_archived_rows(_mock_embed: object) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_active = f"td-arch-active-{suffix}"
    task_archived = f"td-arch-archived-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await embed_task_outcome(
                task_id=task_active,
                description=f"active row marker {suffix}",
                summary="stays visible",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            await embed_task_outcome(
                task_id=task_archived,
                description=f"archived row marker {suffix}",
                summary="must disappear once archived",
                outcome="completed",
                files_changed=[],
                db=session,
            )
            await _mark_archived(session, task_archived)

            results = await query_similar_tasks(
                "irrelevant query text", session, top_k=1000
            )
            task_ids = {r["task_id"] for r in results}
            assert task_active in task_ids
            assert task_archived not in task_ids

            await session.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id.in_([task_active, task_archived])
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_query_architecture_notes_excludes_archived_rows(
    _mock_embed: object,
) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_archived = f"td-arch-note-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await embed_architecture_note(
                task_id=task_archived,
                content=f"an architecture note {suffix}",
                db=session,
            )
            await _mark_archived(session, task_archived)

            results = await query_architecture_notes("irrelevant", session, top_k=1000)
            task_ids = {r["task_id"] for r in results}
            assert task_archived not in task_ids

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_archived)
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_query_failures_excludes_archived_rows(_mock_embed: object) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_archived = f"td-arch-fail-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await embed_failure(
                task_id=task_archived,
                error_description=f"an error {suffix}",
                root_cause="a root cause",
                db=session,
            )
            await _mark_archived(session, task_archived)

            results = await query_failures("irrelevant", session, top_k=1000)
            task_ids = {r["task_id"] for r in results}
            assert task_archived not in task_ids

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_archived)
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_query_learning_signals_excludes_archived_rows(
    _mock_embed: object,
) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    agent_name = f"arch-learn-agent-{suffix}"
    task_id = f"fleet-{agent_name}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await embed_learning_signal(
                agent_name=agent_name,
                description=f"an action {suffix}",
                outcome_summary="an outcome",
                db=session,
            )
            await _mark_archived(session, task_id)

            results = await query_learning_signals("irrelevant", session, top_k=1000)
            agent_names = {r["agent_name"] for r in results}
            assert agent_name not in agent_names

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_id)
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_query_procedures_excludes_archived_rows(_mock_embed: object) -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_archived = f"td-arch-proc-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await embed_procedure(
                task_id=task_archived,
                symptom=f"a symptom {suffix}",
                steps_taken=["step one", "step two"],
                resolution="a resolution",
                agent_name="tester",
                db=session,
            )
            await _mark_archived(session, task_archived)

            results = await query_procedures("irrelevant", session, top_k=1000)
            task_ids = {r["task_id"] for r in results}
            assert task_archived not in task_ids

            await session.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_archived)
            )
            await session.commit()
    finally:
        await engine.dispose()


@patch("app.memory.store._embed", side_effect=_vector_for)
def test_real_retention_job_output_is_actually_excluded_end_to_end(
    _mock_embed: object,
) -> None:
    """Ties the two halves together: app.services.retention._archive_table
    (the real function _run_cleanup calls for memory_embeddings specifically
    — called directly here, not via enforce_retention_policy(), so this test
    doesn't also flip archived=true on unrelated real task_logs/agent_runs/
    artifacts rows in this shared dev DB) archives an old-enough row, and
    query_similar_tasks then genuinely never returns it — not a simulated
    archived flag.

    A plain sync test using asyncio.run() per step (not @pytest.mark.asyncio),
    resetting app.db.session's cached engine/session-factory singleton before
    calling _archive_table — the exact documented convention
    test_retention_archive.py already established for this same hazard:
    _archive_table uses the process-wide get_session_factory() singleton,
    which — if some earlier test in the suite already initialized it — is
    bound to that earlier test's now-closed event loop, not this test's.
    """
    import asyncio
    from datetime import datetime, timedelta, timezone

    suffix = uuid.uuid4().hex[:8]
    task_old = f"td-retain-old-{suffix}"

    async def _setup_and_backdate() -> None:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await embed_task_outcome(
                    task_id=task_old,
                    description="an old row",
                    summary="old enough to be retention-archived",
                    outcome="completed",
                    files_changed=[],
                    db=session,
                )
                # Backdate created_at past the retention cutoff — the row
                # itself is real, only its age is simulated (no
                # time.sleep(90 days)).
                await session.execute(
                    text(
                        "UPDATE memory_embeddings SET created_at = now() - interval '200 days' "
                        "WHERE task_id = :task_id"
                    ),
                    {"task_id": task_old},
                )
                await session.commit()
        finally:
            await engine.dispose()

    async def _run_archival() -> int:
        import app.db.session as _sess

        _sess._engine = None
        _sess._session_factory = None
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=90)
        return await _archive_table("memory_embeddings", "created_at", cutoff)

    async def _verify_and_cleanup() -> set[str]:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                results = await query_similar_tasks(
                    "irrelevant query text", session, top_k=1000
                )
                task_ids = {r["task_id"] for r in results}
                await session.execute(
                    delete(MemoryEmbedding).where(MemoryEmbedding.task_id == task_old)
                )
                await session.commit()
                return task_ids
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup_and_backdate())
        archived_count = asyncio.run(_run_archival())
        assert archived_count >= 1
        task_ids = asyncio.run(_verify_and_cleanup())
        assert task_old not in task_ids
    finally:
        # Gap-closure Day 10 (Gap Audit Protocol, first checkpoint):
        # _run_archival() above resets the global engine/session-factory
        # singleton *before* calling _archive_table so that call gets one
        # bound to this test's own event loop — but left it bound there
        # afterward, still pointing at this test's now-closing event loop
        # for the rest of the process. Reproduced live: running this test
        # before test_repo_scoping_race_fix.py (whose _dispatch_decision
        # also calls get_session_factory()) failed that later test with
        # "RuntimeError: Event loop is closed". Resetting again here means
        # whichever test runs next gets a freshly bound engine.
        import app.db.session as _sess

        _sess._engine = None
        _sess._session_factory = None
