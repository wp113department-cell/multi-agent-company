"""Real-DB integration test for AUDIT_Q_BATCH15 §117 gap-closure.

Proves the full path end to end against real Postgres: a Repo with a real
DevTask, a real AgentRun scoped to it, and a real AgentBenchmark baseline row
-> compute_agents_score's real join -> store_agents_score's real persistence
(migration 042) -> get_latest_agents_score's real read-back ->
quality_score.get_quality_score() picks it up as an "available" category.
Mirrors test_stage4_cluster_q_quality_score_aggregation.py's own
real-Postgres, real-store-function convention (never hand-inserting rows via
raw SQL for the layer under test).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import AgentBenchmark, AgentRun, AgentsScore, DevTask, Repo
from app.db.session import new_isolated_async_engine
from app.fleet.agents_score import (
    compute_agents_score,
    get_latest_agents_score,
    store_agents_score,
)
from app.fleet.quality_score import get_quality_score


def _setup_sync(suffix: str) -> tuple[int, int, str]:
    async def _run() -> tuple[int, int, str]:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                repo = Repo(
                    github_url=f"https://github.com/test/batch15-agents-{suffix}",
                    name=f"batch15-agents-{suffix}",
                    local_path=f"/tmp/batch15-agents-{suffix}",
                    status="ready",
                )
                db.add(repo)
                await db.commit()
                await db.refresh(repo)

                agent_name = f"td_agent_{suffix}"
                task = DevTask(
                    title="test task",
                    description="test",
                    repo_id=repo.id,
                    status="completed",
                )
                db.add(task)
                await db.commit()
                await db.refresh(task)

                run = AgentRun(
                    id=str(uuid.uuid4()),
                    task_id=task.id,
                    agent_type=agent_name,
                    status="completed",
                )
                db.add(run)

                benchmark = AgentBenchmark(
                    agent_name=agent_name,
                    objectives={"benchmark_score": 0.75},
                    is_baseline=True,
                )
                db.add(benchmark)
                await db.commit()

                return int(repo.id), int(task.id), agent_name
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _cleanup_sync(repo_id: int, task_id: int, agent_name: str) -> None:
    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                await db.execute(
                    delete(AgentsScore).where(AgentsScore.repo_id == repo_id)
                )
                await db.execute(
                    delete(AgentBenchmark).where(
                        AgentBenchmark.agent_name == agent_name
                    )
                )
                await db.execute(delete(AgentRun).where(AgentRun.task_id == task_id))
                await db.execute(delete(DevTask).where(DevTask.id == task_id))
                await db.execute(delete(Repo).where(Repo.id == repo_id))
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_agents_score_end_to_end_real_join_persist_and_aggregate() -> None:
    suffix = uuid.uuid4().hex[:8]
    repo_id, task_id, agent_name = _setup_sync(suffix)

    try:
        # 1. Before any agents_score row exists: quality_score reports "no_data".
        before = get_quality_score(repo_id)
        by_name = {c.name: c for c in before.categories}
        assert by_name["agents"].status == "unavailable"
        assert by_name["agents"].reason == "no_data"

        # 2. Real compute (real join through agent_runs -> dev_tasks -> repo_id,
        # real baseline lookup) against a real session.
        async def _compute() -> Any:
            engine = new_isolated_async_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                    return await compute_agents_score(repo_id, db)
            finally:
                await engine.dispose()

        result = asyncio.run(_compute())
        assert result is not None
        assert result.agent_names == [agent_name]
        assert result.agents_score == 0.75
        # store_agents_score is sync-facing (its own asyncio.run() inside) —
        # must be called from plain sync code, same as its real caller
        # (main.py's _agents_score_compute_loop uses asyncio.to_thread() for
        # exactly this reason).
        store_agents_score(repo_id, result)

        # 3. Real persisted read-back.
        latest = get_latest_agents_score(repo_id)
        assert latest is not None
        assert latest.agents_score == 0.75
        assert agent_name in latest.per_agent_scores

        # 4. quality_score's cross-category aggregator now sees a real,
        # available "agents" category — never recomputed, only read.
        after = get_quality_score(repo_id)
        by_name = {c.name: c for c in after.categories}
        assert by_name["agents"].status == "available"
        assert by_name["agents"].score == 0.75
        assert after.overall_score == 0.75
    finally:
        _cleanup_sync(repo_id, task_id, agent_name)
