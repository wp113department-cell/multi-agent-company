"""Stage 4 Cluster O Phase 1b (2026-08-05) — real end-to-end proof, against
at least 2 real repositories, that the 4 remaining change points
CLUSTER_O_DESIGN.md's §7/§1.4 named (D: manager.py epics, E: ChatSession/
chat_agent.py, F: architect.py, G: pipeline/graph.py's run_planning_pipeline)
correctly resolve and thread repo_id, mirroring Phase 1a's own real-DB,
no-mocked-DB, 2-repo isolation standard
(test_cluster_o_repo_scoped_memory_isolation.py).

Each change point's graph/LLM layer is short-circuited the same way this
suite's own existing precedents already do — not invented here:
  - G, D(_planning_node): get_graph() patched to a fake ainvoke that just
    captures the initial_state and returns immediately, matching
    tests/test_task_images.py::test_run_planning_pipeline_populates_images_from_db
    exactly (proves the real pre-graph memory-context code, not the LLM).
  - F: app.agents.architect.run_agent_graph patched to return a submitted
    state, matching tests/test_day18_streaming_wiring.py's own
    test_architect_node_passes_task_id pattern exactly.
  - D(_finalize_node): no LLM/graph involved at all — called directly with
    a hand-built EpicManagerState.
  - E: ChatSession constructed directly with an explicit repo_id (the
    resolve_repo_id_from_path() step itself is tested separately below,
    real DB, no mocking) and ChatAgent._memory_read_context/_memory_write_outcome
    called directly — no chat SSE/streaming harness needed for what's
    being proven here.

_embed is mocked with a deterministic content-derived vector, same
rationale as Phase 1a's test file (VOYAGE_API_KEY unset in this
environment).
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.agents.architect import architect_node
from app.agents.chat_agent import ChatAgent
from app.agents.manager import EpicManagerState, _finalize_node, _planning_node
from app.config import get_settings
from app.db.models import DevTask, MemoryEmbedding, Repo
from app.db.repository import create_task, resolve_repo_id_from_path
from app.db.session import new_isolated_async_engine
from app.models.chat import ChatSession
from app.memory.store import embed_task_outcome, query_similar_tasks

_SUBMITTED_ARCHITECT_STATE = {
    "messages": [],
    "verification": {},
    "result": {
        "technical_approach": "x",
        "impacted_files": [],
        "risks": [],
        "risk_level": "low",
    },
    "turns": 1,
    "submitted": True,
    "requires_human_approval": False,
    "tokens_in": 10,
    "tokens_out": 10,
}


def _vector_for(text_to_embed: str) -> list[float]:
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _make_repo(session: AsyncSession, suffix: str) -> int:
    repo = Repo(
        github_url=f"https://github.com/test/clustero-1b-{suffix}",
        name=f"clustero-1b-{suffix}",
        local_path=f"/tmp/clustero-1b-{suffix}",
        status="ready",
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return int(repo.id)


async def _cleanup(
    session: AsyncSession, task_ids: list[str], repo_ids: list[int]
) -> None:
    if task_ids:
        await session.execute(
            delete(MemoryEmbedding).where(MemoryEmbedding.task_id.in_(task_ids))
        )
    if repo_ids:
        await session.execute(delete(DevTask).where(DevTask.repo_id.in_(repo_ids)))
        await session.execute(delete(Repo).where(Repo.id.in_(repo_ids)))
    await session.commit()


def _make_repo_sync(suffix: str) -> int:
    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await _make_repo(session, suffix)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _real_task_id_sync(title: str, repo_id: int | None) -> int:
    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                task = await create_task(session, title, "desc", repo_id=repo_id)
                return task.id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _cleanup_sync(task_ids: list[int], repo_ids: list[int]) -> None:
    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                if task_ids:
                    await session.execute(
                        delete(MemoryEmbedding).where(
                            MemoryEmbedding.task_id.in_([str(t) for t in task_ids])
                        )
                    )
                    await session.execute(
                        delete(DevTask).where(DevTask.id.in_(task_ids))
                    )
                if repo_ids:
                    await session.execute(delete(Repo).where(Repo.id.in_(repo_ids)))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Change point G — run_planning_pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_run_planning_pipeline_memory_context_never_leaks_across_repos(
    _mock_embed: object,
) -> None:
    """get_graph() short-circuited (same trick as
    test_task_images.py::test_run_planning_pipeline_populates_images_from_db)
    so this proves the real pre-graph memory-context code, not the LLM."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    marker_a = f"CLUSTERO_1B_MARKER_A_{suffix}"
    marker_b = f"CLUSTERO_1B_MARKER_B_{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = await _make_repo(session, f"g-a-{suffix}")
            repo_b = await _make_repo(session, f"g-b-{suffix}")
            task_a = await create_task(session, f"g-a-{suffix}", "d", repo_id=repo_a)
            task_b = await create_task(session, f"g-b-{suffix}", "d", repo_id=repo_b)

            await embed_task_outcome(
                task_id=str(task_a.id),
                description=marker_a,
                summary=marker_a,
                outcome="completed",
                files_changed=[],
                db=session,
                repo_id=repo_a,
            )
            await embed_task_outcome(
                task_id=str(task_b.id),
                description=marker_b,
                summary=marker_b,
                outcome="completed",
                files_changed=[],
                db=session,
                repo_id=repo_b,
            )

            from app.pipeline import graph as graph_module

            for task, other_marker in ((task_a, marker_b), (task_b, marker_a)):
                captured_state: dict[str, Any] = {}

                async def _fake_ainvoke(state: Any, config: Any) -> Any:
                    captured_state.update(state)
                    return {**state, "stage": "blocked", "error": "short-circuit"}

                fake_graph = MagicMock()
                fake_graph.ainvoke = AsyncMock(side_effect=_fake_ainvoke)

                with patch.object(graph_module, "get_graph", return_value=fake_graph):
                    await graph_module.run_planning_pipeline(
                        task_id=task.id,
                        title="t",
                        description="d",
                        repo_path="/tmp",
                        db=session,
                    )

                assert other_marker not in captured_state["memory_context"], (
                    f"the other repo's marker leaked into task {task.id}'s "
                    "pre-planning memory_context"
                )

            await _cleanup(session, [str(task_a.id), str(task_b.id)], [repo_a, repo_b])
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Change point F — architect_node
# ---------------------------------------------------------------------------


def test_architect_node_writes_distinct_repo_id_per_task() -> None:
    """app.agents.architect.run_agent_graph patched to return a submitted
    state directly (same pattern as
    test_day18_streaming_wiring.py::test_architect_node_passes_task_id) —
    proves architect_node's own embed_architecture_note_sync call, not the
    LLM. Plain sync test (not @pytest.mark.asyncio): architect_node is
    itself a sync function calling get_task_repo_id_sync's own
    asyncio.run() internally, which cannot be nested inside an
    already-running event loop — same reasoning as Phase 1a's own
    run_agent_graph()-touching tests."""
    suffix = uuid.uuid4().hex[:8]
    repo_a = _make_repo_sync(f"f-a-{suffix}")
    repo_b = _make_repo_sync(f"f-b-{suffix}")
    task_a = _real_task_id_sync(f"f-a-{suffix}", repo_a)
    task_b = _real_task_id_sync(f"f-b-{suffix}", repo_b)

    try:
        with patch("app.memory.store._embed", side_effect=_vector_for):
            for task_id, expected_repo in ((task_a, repo_a), (task_b, repo_b)):
                state = {
                    "task_id": task_id,
                    "task_title": f"arch-{task_id}",
                    "pm_brief": {},
                    "repo_path": "/tmp",
                }
                with patch(
                    "app.agents.architect.run_agent_graph",
                    return_value=_SUBMITTED_ARCHITECT_STATE,
                ):
                    architect_node(state)  # type: ignore[arg-type]

        async def _fetch(task_id: int) -> MemoryEmbedding | None:
            engine = new_isolated_async_engine()
            try:
                async with async_sessionmaker(
                    engine, expire_on_commit=False
                )() as session:
                    result = await session.execute(
                        select(MemoryEmbedding).where(
                            MemoryEmbedding.task_id == str(task_id)
                        )
                    )
                    return result.scalar_one_or_none()
            finally:
                await engine.dispose()

        row_a = asyncio.run(_fetch(task_a))
        row_b = asyncio.run(_fetch(task_b))
        assert row_a is not None, "architect_node did not write a row for task A"
        assert row_b is not None, "architect_node did not write a row for task B"
        assert row_a.repo_id == repo_a
        assert row_b.repo_id == repo_b
    finally:
        _cleanup_sync([task_a, task_b], [repo_a, repo_b])


# ---------------------------------------------------------------------------
# Change point D — manager.py's epic-manager graph nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planning_node_honestly_reads_the_newly_created_tasks_repo_id() -> None:
    """CLUSTER_O_DESIGN.md's Phase 1b notes originally documented that
    CreateEpicRequest/Epic had no repo_id field, so _planning_node's
    internally-created DevTask never got one set. Stage 4 Cluster R Phase 2
    (2026-08-05, CLUSTER_R_DESIGN.md) closed that gap: epics can now carry
    a real repo_id, and _planning_node inherits it via
    state.get("repo_id"). This test exercises the still-real legacy path —
    a state dict with no "repo_id" key at all (the exact shape a
    repo_id=NULL epic produces) — and confirms the DevTask it creates
    stays correctly unscoped (repo_id=None), not that the field is
    unimplemented. The scoped path (a real repo_id flowing through to the
    created DevTask) is covered by
    tests/test_stage4_cluster_r_epic_repo_id_execution_path.py."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            from app.db.models import Epic
            from app.pipeline import graph as graph_module

            # dev_tasks.epic_id has a real FK to epics.epic_id — _planning_node's
            # internal DevTask(...) insert needs a real parent row.
            epic_id = str(uuid.uuid4())
            epic = Epic(
                epic_id=epic_id,
                title=f"clustero 1b planning {suffix}",
                description="d",
                status="pending",
            )
            session.add(epic)
            await session.commit()

            async def _fake_ainvoke(state: Any, config: Any) -> Any:
                return {**state, "subtasks": [], "task_description": "d"}

            fake_graph = MagicMock()
            fake_graph.ainvoke = AsyncMock(side_effect=_fake_ainvoke)

            state: EpicManagerState = {
                "epic_id": epic_id,
                "goal": f"clustero 1b planning {suffix}",
                "db": session,
                "repo": "/tmp",
            }
            with patch.object(graph_module, "get_graph", return_value=fake_graph):
                result = await _planning_node(state)

            assert "repo_id" in result
            assert result["repo_id"] is None  # legacy/unscoped epic path

            await session.execute(
                delete(DevTask).where(DevTask.id == result["task_id"])
            )
            await session.execute(delete(Epic).where(Epic.epic_id == epic_id))
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_finalize_node_threads_state_repo_id_into_embed_task_outcome(
    _mock_embed: object,
) -> None:
    """Proves the forward-compatible half of the claim above: whatever
    real repo_id ends up in EpicManagerState["repo_id"] (from a future
    epic-scoping mechanism, or a test asserting the wiring directly, as
    here) reaches the real embed_task_outcome call correctly and distinctly
    for 2 real repos — no LLM or subtask execution involved, _finalize_node
    is pure DB writes."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    settings = get_settings()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = await _make_repo(session, f"d-a-{suffix}")
            repo_b = await _make_repo(session, f"d-b-{suffix}")

            # Synthetic task_ids, no real DevTask row needed (MemoryEmbedding.
            # task_id is a free-text column, not FK-constrained) — derived
            # from this test's own random suffix to rule out any collision
            # with another test's rows in this shared DB.
            base = int(suffix, 16) % 900_000_000 + 100_000_000
            synth_task_ids = (base, base + 1)

            for synth_task_id, repo_id in zip(synth_task_ids, (repo_a, repo_b)):
                state: EpicManagerState = {
                    "epic_id": str(uuid.uuid4()),  # epics.epic_id is a real UUID column
                    "goal": f"clustero 1b finalize {suffix}",
                    "db": session,
                    "task_id": synth_task_id,
                    "subtasks": [],
                    "settings": settings,
                    "repo_id": repo_id,
                    "manager_result": {
                        "status": "completed",
                        "results": [],
                        "blocked_count": 0,
                        "tokens_in": 0,
                        "tokens_out": 0,
                    },
                }
                await _finalize_node(state)

            results_a = await query_similar_tasks(
                "irrelevant", session, top_k=1000, repo_id=repo_a
            )
            ids_a = {r["task_id"] for r in results_a}
            results_b = await query_similar_tasks(
                "irrelevant", session, top_k=1000, repo_id=repo_b
            )
            ids_b = {r["task_id"] for r in results_b}

            str_ids = [str(t) for t in synth_task_ids]
            assert str_ids[0] in ids_a
            assert str_ids[1] not in ids_a
            assert str_ids[1] in ids_b
            assert str_ids[0] not in ids_b

            await _cleanup(session, str_ids, [repo_a, repo_b])
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Change point E — ChatSession / chat_agent.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_repo_id_from_path_finds_correct_repo_for_two_real_repos() -> (
    None
):
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = await _make_repo(session, f"resolve-e-a-{suffix}")
            repo_b = await _make_repo(session, f"resolve-e-b-{suffix}")

            resolved_a = await resolve_repo_id_from_path(
                session, f"/tmp/clustero-1b-resolve-e-a-{suffix}"
            )
            resolved_b = await resolve_repo_id_from_path(
                session, f"/tmp/clustero-1b-resolve-e-b-{suffix}"
            )
            assert resolved_a == repo_a
            assert resolved_b == repo_b

            unknown = await resolve_repo_id_from_path(
                session, f"/tmp/does-not-exist-{suffix}"
            )
            assert unknown is None

            await session.execute(delete(Repo).where(Repo.id.in_([repo_a, repo_b])))
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_chat_agent_memory_read_never_leaks_across_two_real_repos(
    _mock_embed: object,
) -> None:
    """The leak-proof test for chat: two real repos, each with a
    uniquely-markered memory row, and ChatAgent._memory_read_context for a
    session scoped to repo A must never surface repo B's marker (asserted
    on absence, same deterministic reasoning as Phase 1a's own leak test)."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    marker_a = f"CLUSTERO_1B_CHAT_MARKER_A_{suffix}"
    marker_b = f"CLUSTERO_1B_CHAT_MARKER_B_{suffix}"
    task_a = f"chat-td-a-{suffix}"
    task_b = f"chat-td-b-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = await _make_repo(session, f"chat-a-{suffix}")
            repo_b = await _make_repo(session, f"chat-b-{suffix}")

            await embed_task_outcome(
                task_id=task_a,
                description=marker_a,
                summary=marker_a,
                outcome="completed",
                files_changed=[],
                db=session,
                repo_id=repo_a,
            )
            await embed_task_outcome(
                task_id=task_b,
                description=marker_b,
                summary=marker_b,
                outcome="completed",
                files_changed=[],
                db=session,
                repo_id=repo_b,
            )

            session_a = ChatSession(
                session_id=f"chat-sess-a-{suffix}", repo_path="/tmp", repo_id=repo_a
            )
            session_b = ChatSession(
                session_id=f"chat-sess-b-{suffix}", repo_path="/tmp", repo_id=repo_b
            )
            agent_a = ChatAgent(session_a)
            agent_b = ChatAgent(session_b)

            with patch("app.memory.store._embed", side_effect=_vector_for):
                context_a = await agent_a._memory_read_context("irrelevant query")
                context_b = await agent_b._memory_read_context("irrelevant query")

            assert (
                marker_b not in context_a
            ), "repo B's memory leaked into repo A's chat session context"
            assert (
                marker_a not in context_b
            ), "repo A's memory leaked into repo B's chat session context"

            await _cleanup(session, [task_a, task_b], [repo_a, repo_b])
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_chat_agent_memory_write_outcome_writes_distinct_repo_id(
    _mock_embed: object,
) -> None:
    """The write-side counterpart — two real ChatSessions scoped to two
    real repos, _memory_write_outcome writes a distinctly-scoped row for
    each."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    session_id_a = f"chat-write-a-{suffix}"
    session_id_b = f"chat-write-b-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = await _make_repo(session, f"chat-write-a-{suffix}")
            repo_b = await _make_repo(session, f"chat-write-b-{suffix}")

            chat_session_a = ChatSession(
                session_id=session_id_a, repo_path="/tmp", repo_id=repo_a
            )
            chat_session_b = ChatSession(
                session_id=session_id_b, repo_path="/tmp", repo_id=repo_b
            )
            agent_a = ChatAgent(chat_session_a)
            agent_b = ChatAgent(chat_session_b)

            await agent_a._memory_write_outcome("desc A", "summary A", None)
            await agent_b._memory_write_outcome("desc B", "summary B", None)

            results_a = await query_similar_tasks(
                "irrelevant", session, top_k=1000, repo_id=repo_a
            )
            ids_a = {r["task_id"] for r in results_a}
            results_b = await query_similar_tasks(
                "irrelevant", session, top_k=1000, repo_id=repo_b
            )
            ids_b = {r["task_id"] for r in results_b}

            assert session_id_a in ids_a
            assert session_id_b not in ids_a
            assert session_id_b in ids_b
            assert session_id_a not in ids_b

            await _cleanup(session, [session_id_a, session_id_b], [repo_a, repo_b])
    finally:
        await engine.dispose()
