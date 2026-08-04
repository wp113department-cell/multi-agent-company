"""Stage 4 Cluster O Phase 1a (2026-08-05) — real end-to-end proof, against
at least 2 real repositories, that the repo_id CLUSTER_O_DESIGN.md's Phase
1a actually wired (run_agent_graph's AgentRunState + memory_hook_node +
_maybe_store_procedure; record_agent_run_outcome's 3 embed_* calls;
get_task_repo_id/_sync) is resolved correctly and never crosses repos.

This file does NOT re-prove app/memory/store.py's own SQL filter —
tests/test_memory_project_scoping_queries.py (gap-closure Day 3) already
does that at the store.py layer directly. What's new here is the CALL-SITE
WIRING Phase 1a added: does a real DevTask's repo_id actually reach those
functions through the real chokepoints, not just work when passed by hand.

Three properties CLUSTER_O_DESIGN.md's approval asked to be proven here:
  1. repository-scoped memories never leak across repositories
  2. intentionally global learning still behaves as designed
  3. mixed workloads (scoped A + scoped B + global, together) remain correct

Two test styles, matching each existing precedent this file builds on:
  - `@pytest.mark.asyncio async def` for direct app/memory/store.py-level
    calls (test_memory_project_scoping_queries.py's own convention).
  - plain sync `def` for anything touching a _sync bridge
    (get_task_repo_id_sync, run_agent_graph) — asyncio.run() inside those
    cannot be called from within an already-running event loop, so they
    must be exercised from a synchronous test, matching
    test_stage4_clustern_real_agent_run_heartbeat.py's own established
    convention exactly.

_embed is mocked with a deterministic content-derived vector (not the DB),
since VOYAGE_API_KEY is unset in this environment and the real zero-vector
short-circuit would otherwise make every query return [] regardless of the
WHERE clause under test — see test_memory_project_scoping_queries.py's
docstring for the full rationale, mirrored verbatim here.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.agents.agent_result import AgentResult
from app.agents.base_graph import VerificationConfig, run_agent_graph
from app.config import get_settings
from app.db.models import DevTask, MemoryEmbedding, Repo
from app.db.repository import create_task, get_task_repo_id, get_task_repo_id_sync
from app.db.session import new_isolated_async_engine
from app.memory.hooks import record_agent_run_outcome
from app.memory.store import (
    embed_learning_signal,
    embed_task_outcome,
    query_learning_signals,
    query_similar_tasks,
)

DO_NOTHING_TOOL = {
    "name": "submit_result",
    "description": "Submit",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
    },
}


def _vector_for(text_to_embed: str) -> list[float]:
    """Deterministic, content-derived fake embedding — identical helper to
    test_memory_project_scoping_queries.py's own (kept local rather than
    imported: each real-DB test file in this suite defines its own fixture
    helpers, matching that file's and test_repo_scoping_race_fix.py's own
    convention)."""
    seed = int(hashlib.sha256(text_to_embed.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _make_repo(session: AsyncSession, suffix: str) -> int:
    repo = Repo(
        github_url=f"https://github.com/test/clustero-{suffix}",
        name=f"clustero-{suffix}",
        local_path=f"/tmp/clustero-{suffix}",
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


class _ImmediateSubmitLLM:
    """Submits on the very first call — this suite doesn't need tool-call
    iteration, only that the run completes and threads repo_id end to end.
    Same shape as _ScriptedLLM in test_stage4_clustern_real_agent_run_heartbeat.py."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use",
                    id="tu_submit",
                    name="submit_result",
                    input={"summary": "done"},
                )
            ],
            usage=SimpleNamespace(input_tokens=20, output_tokens=5),
        )


def _real_task_id_sync(title: str, repo_id: int | None) -> int:
    """Sync helper — creates a real DevTask scoped to repo_id via the same
    isolated-engine bridge pattern as _real_task_id in
    test_stage4_clustern_real_agent_run_heartbeat.py, extended to accept
    repo_id (that file's own helper never needed one)."""

    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                task = await create_task(session, title, "desc", repo_id=repo_id)
                return task.id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _make_repo_sync(suffix: str) -> int:
    async def _run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await _make_repo(session, suffix)
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


def _run_scripted_agent_for_task(task_id: int) -> Any:
    with patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"), patch(
        "anthropic.Anthropic"
    ) as mock_anthropic_cls, patch("app.memory.store._embed", side_effect=_vector_for):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _ImmediateSubmitLLM()
        mock_anthropic_cls.return_value = mock_client

        return run_agent_graph(
            role_name="clustero_test_agent",
            model="claude-haiku-4-5-20251001",
            tools=[DO_NOTHING_TOOL],
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=VerificationConfig(),
            initial_message="do a task",
            enable_planning=False,
            enable_memory=True,
            enable_reflection=False,
            enable_lesson=False,
            enable_run_tracking=False,  # not testing Cluster N here
            max_turns=5,
            task_id=str(task_id),
        )


# ---------------------------------------------------------------------------
# 1. Repository-scoped memories never leak — through the real
#    run_agent_graph() chokepoint (change point C), not store.py directly.
# ---------------------------------------------------------------------------


def test_run_agent_graph_resolves_correct_distinct_repo_id_per_task() -> None:
    """The core Phase 1a wiring proof: two real repos, two real tasks, and
    run_agent_graph() must resolve each task's OWN repo_id — never the
    other's, never a stale/cached wrong value."""
    suffix = uuid.uuid4().hex[:8]
    repo_a = _make_repo_sync(f"e2e-a-{suffix}")
    repo_b = _make_repo_sync(f"e2e-b-{suffix}")
    task_a = _real_task_id_sync(f"clustero e2e A {suffix}", repo_a)
    task_b = _real_task_id_sync(f"clustero e2e B {suffix}", repo_b)

    try:
        final_a = _run_scripted_agent_for_task(task_a)
        final_b = _run_scripted_agent_for_task(task_b)

        assert final_a["repo_id"] == repo_a
        assert final_a["repo_id"] != repo_b
        assert final_b["repo_id"] == repo_b
        assert final_b["repo_id"] != repo_a
    finally:
        _cleanup_sync([task_a, task_b], [repo_a, repo_b])


def test_run_agent_graph_repo_id_defaults_to_none_for_synthetic_task_id() -> None:
    """INV-8: an unresolvable task_id (e.g. a guardian agent's synthetic
    id) must degrade to unscoped/global, never raise and never crash the
    run."""
    with patch("app.agents.base_graph.load_role", return_value="# Test Agent\n"), patch(
        "anthropic.Anthropic"
    ) as mock_anthropic_cls, patch("app.memory.store._embed", side_effect=_vector_for):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _ImmediateSubmitLLM()
        mock_anthropic_cls.return_value = mock_client

        final_state = run_agent_graph(
            role_name="clustero_synthetic_task_agent",
            model="claude-haiku-4-5-20251001",
            tools=[DO_NOTHING_TOOL],
            tool_handlers={"submit_result": lambda inp: "ok"},
            verification_cfg=VerificationConfig(),
            initial_message="do a task",
            enable_planning=False,
            enable_memory=True,
            enable_reflection=False,
            enable_lesson=False,
            enable_run_tracking=False,
            max_turns=5,
            task_id="fleet-scan",  # synthetic, not a real dev_tasks id
        )
    assert final_state["repo_id"] is None
    assert final_state["submitted"] is True


def test_run_agent_graph_memory_context_never_contains_the_other_repos_marker() -> None:
    """The property that actually matters: seed repo A and repo B each with
    a uniquely-markered memory row, run the real agent against task A, and
    prove repo B's marker is absent from the injected memory_context —
    tested for ABSENCE (not presence-in-top-3), which is deterministic
    regardless of the composite-score ranking algorithm (a WHERE-clause
    fact, not a ranking fact) and therefore cannot flake against a shared
    test database with other tests' own rows in it."""
    suffix = uuid.uuid4().hex[:8]
    repo_a = _make_repo_sync(f"leak-a-{suffix}")
    repo_b = _make_repo_sync(f"leak-b-{suffix}")
    task_a = _real_task_id_sync(f"clustero leak A {suffix}", repo_a)
    task_b = _real_task_id_sync(f"clustero leak B {suffix}", repo_b)
    marker_a = f"CLUSTERO_MARKER_A_{suffix}"
    marker_b = f"CLUSTERO_MARKER_B_{suffix}"

    async def _seed() -> None:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                with patch("app.memory.store._embed", side_effect=_vector_for):
                    await embed_task_outcome(
                        task_id=str(task_a),
                        description=marker_a,
                        summary=marker_a,
                        outcome="completed",
                        files_changed=[],
                        db=session,
                        repo_id=repo_a,
                    )
                    await embed_task_outcome(
                        task_id=str(task_b),
                        description=marker_b,
                        summary=marker_b,
                        outcome="completed",
                        files_changed=[],
                        db=session,
                        repo_id=repo_b,
                    )
        finally:
            await engine.dispose()

    asyncio.run(_seed())

    try:
        final_a = _run_scripted_agent_for_task(task_a)
        final_b = _run_scripted_agent_for_task(task_b)

        context_a = final_a.get("memory_context", "")
        context_b = final_b.get("memory_context", "")

        assert (
            marker_b not in context_a
        ), "repo B's memory leaked into repo A's agent run's injected context"
        assert (
            marker_a not in context_b
        ), "repo A's memory leaked into repo B's agent run's injected context"
    finally:
        _cleanup_sync([task_a, task_b], [repo_a, repo_b])


# ---------------------------------------------------------------------------
# 2. record_agent_run_outcome (change point A/B) threads repo_id correctly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_record_agent_run_outcome_writes_distinct_repo_id_per_call(
    _mock_embed: object,
) -> None:
    """The chokepoint most of the ~55-agent specialized_agents.py dispatch
    fleet writes memory through — proves a caller-supplied repo_id reaches
    all the way to the real DB row, for two different repos in the same
    test."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_a = f"td-hook-a-{suffix}"
    task_b = f"td-hook-b-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = await _make_repo(session, f"hook-a-{suffix}")
            repo_b = await _make_repo(session, f"hook-b-{suffix}")

            await record_agent_run_outcome(
                agent_name="clustero_test_agent",
                task_id=task_a,
                description=f"hook marker A {suffix}",
                result=AgentResult(summary="done A", status="completed"),
                db=session,
                repo_id=repo_a,
            )
            await record_agent_run_outcome(
                agent_name="clustero_test_agent",
                task_id=task_b,
                description=f"hook marker B {suffix}",
                result=AgentResult(summary="done B", status="completed"),
                db=session,
                repo_id=repo_b,
            )

            results_a = await query_similar_tasks(
                "irrelevant", session, top_k=1000, repo_id=repo_a
            )
            ids_a = {r["task_id"] for r in results_a}
            assert task_a in ids_a
            assert task_b not in ids_a

            results_b = await query_similar_tasks(
                "irrelevant", session, top_k=1000, repo_id=repo_b
            )
            ids_b = {r["task_id"] for r in results_b}
            assert task_b in ids_b
            assert task_a not in ids_b

            await _cleanup(session, [task_a, task_b], [repo_a, repo_b])
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 3. Intentionally global learning still behaves as designed — never
#    scoped, visible from every repo, regardless of which repo the writing
#    agent happened to be operating on.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_learning_signal_stays_global_across_two_real_repos(
    _mock_embed: object,
) -> None:
    """CLUSTER_O_DESIGN.md INV-2/§1.4: fleet-wide learning signals are
    deliberately never repo_id-scoped. Proves the DESIGN decision holds in
    practice: one signal written with no repo_id must be visible from BOTH
    real repos' own queries, not accidentally invisible to either."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    marker = f"CLUSTERO_LEARNING_MARKER_{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = await _make_repo(session, f"learn-a-{suffix}")
            repo_b = await _make_repo(session, f"learn-b-{suffix}")

            await embed_learning_signal(
                agent_name="clustero_test_agent",
                description=marker,
                outcome_summary="a tool timeout pattern, not about any repo's code",
                db=session,
                # repo_id intentionally omitted — matches the real
                # record_learning tool / fleet_dashboard.py call sites.
            )

            results_from_a = await query_learning_signals(
                "irrelevant", session, top_k=1000, repo_id=repo_a
            )
            results_from_b = await query_learning_signals(
                "irrelevant", session, top_k=1000, repo_id=repo_b
            )
            actions_a = {r["action"] for r in results_from_a}
            actions_b = {r["action"] for r in results_from_b}

            assert (
                marker in actions_a
            ), "a global learning signal must be visible from repo A's own query"
            assert (
                marker in actions_b
            ), "a global learning signal must be visible from repo B's own query"

            await session.execute(
                delete(MemoryEmbedding).where(
                    MemoryEmbedding.task_id == "fleet-clustero_test_agent"
                )
            )
            await session.execute(delete(Repo).where(Repo.id.in_([repo_a, repo_b])))
            await session.commit()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 4. Mixed workload: repo-A-scoped, repo-B-scoped, and global rows all
#    coexist correctly in the same query set.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.memory.store._embed", side_effect=_vector_for)
async def test_mixed_workload_scoped_a_scoped_b_and_global_together(
    _mock_embed: object,
) -> None:
    """One query against a DB containing all three categories at once:
    repo A must see {its own row, the global row} and never repo B's row,
    in a single combined assertion — the realistic production shape (a
    memory table accumulating rows from many repos and the fleet's own
    global learning simultaneously), not three isolated single-category
    tests."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    task_a = f"td-mixed-a-{suffix}"
    task_b = f"td-mixed-b-{suffix}"
    task_legacy = f"td-mixed-legacy-{suffix}"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = await _make_repo(session, f"mixed-a-{suffix}")
            repo_b = await _make_repo(session, f"mixed-b-{suffix}")

            await embed_task_outcome(
                task_id=task_a,
                description=f"mixed workload A {suffix}",
                summary="A",
                outcome="completed",
                files_changed=[],
                db=session,
                repo_id=repo_a,
            )
            await embed_task_outcome(
                task_id=task_b,
                description=f"mixed workload B {suffix}",
                summary="B",
                outcome="completed",
                files_changed=[],
                db=session,
                repo_id=repo_b,
            )
            await embed_task_outcome(
                task_id=task_legacy,
                description=f"mixed workload legacy {suffix}",
                summary="legacy",
                outcome="completed",
                files_changed=[],
                db=session,
                # repo_id omitted — global/legacy category
            )

            results_for_a = await query_similar_tasks(
                "irrelevant", session, top_k=1000, repo_id=repo_a
            )
            ids_for_a = {r["task_id"] for r in results_for_a}

            assert task_a in ids_for_a, "repo A must see its own scoped row"
            assert task_legacy in ids_for_a, "repo A must see the global/legacy row"
            assert task_b not in ids_for_a, "repo A must never see repo B's row"

            await _cleanup(session, [task_a, task_b, task_legacy], [repo_a, repo_b])
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 5. get_task_repo_id / get_task_repo_id_sync — the resolver itself,
#    against 2 real repos, proving no cross-task-id cache contamination.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_task_repo_id_resolves_distinct_values_for_two_real_repos() -> None:
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = await _make_repo(session, f"resolve-a-{suffix}")
            repo_b = await _make_repo(session, f"resolve-b-{suffix}")
            task_a = await create_task(
                session, f"resolve-a-{suffix}", "d", repo_id=repo_a
            )
            task_b = await create_task(
                session, f"resolve-b-{suffix}", "d", repo_id=repo_b
            )

            assert await get_task_repo_id(session, task_a.id) == repo_a
            assert await get_task_repo_id(session, task_b.id) == repo_b
            # Re-resolve in reverse order — proves the per-process cache
            # keys correctly by task_id, not by call order.
            assert await get_task_repo_id(session, task_b.id) == repo_b
            assert await get_task_repo_id(session, task_a.id) == repo_a

            await session.execute(
                delete(DevTask).where(DevTask.id.in_([task_a.id, task_b.id]))
            )
            await session.execute(delete(Repo).where(Repo.id.in_([repo_a, repo_b])))
            await session.commit()
    finally:
        await engine.dispose()


def test_get_task_repo_id_sync_resolves_distinct_values_for_two_real_repos() -> None:
    """Sync-bridge counterpart — the one run_agent_graph() actually calls."""
    suffix = uuid.uuid4().hex[:8]
    repo_a = _make_repo_sync(f"resolve-sync-a-{suffix}")
    repo_b = _make_repo_sync(f"resolve-sync-b-{suffix}")
    task_a = _real_task_id_sync(f"resolve-sync-a-{suffix}", repo_a)
    task_b = _real_task_id_sync(f"resolve-sync-b-{suffix}", repo_b)

    try:
        assert get_task_repo_id_sync(task_a) == repo_a
        assert get_task_repo_id_sync(task_b) == repo_b
        assert get_task_repo_id_sync(task_b) == repo_b
        assert get_task_repo_id_sync(task_a) == repo_a
    finally:
        _cleanup_sync([task_a, task_b], [repo_a, repo_b])


def test_get_task_repo_id_sync_returns_none_for_nonexistent_task() -> None:
    """INV-8: an invalid task_id resolves to None (unscoped fallback), never
    an exception."""
    assert get_task_repo_id_sync(2_147_483_647) is None
