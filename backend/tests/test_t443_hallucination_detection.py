"""#443 (2026-09-28, GRIDIRON_PARTIAL "Detect hallucinating agents /
memory leaks / sync failures").

The audit's own plan scored this "genuinely missing... lowest priority...
treat as a separate research/infrastructure initiative" and named two
distinct sub-problems: (1) hallucination detection — buildable today by
persisting/aggregating a signal this codebase ALREADY computes (#502's
citation_check, previously only logged, never durable or queryable); (2)
memory leaks/sync failures in TARGET repo processes — the plan itself
says there is no existing hook to build on (this platform edits/reviews
code, it doesn't run target apps under sustained load), so that half is
correctly left out of scope, same as #169/#171/#494's "needs new
infrastructure" verdicts elsewhere in this initiative.

This file covers the buildable half end to end: migration 061's new
AgentRun.citation_hallucination_count column, finish_agent_run(_sync)
persisting it, and compute_citation_hallucination_rate's real aggregation
— mirroring test_t2b7_agent_run_performance_metrics.py's own established
real-Postgres, no-mocks convention. The graph-level counter itself
(execute_tools incrementing citation_hallucination_count in state) is
covered separately in test_batch18_citation_verification.py::
TestCitationHallucinationCount.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import AgentRun, DevTask
from app.db.repository import create_agent_run, finish_agent_run
from app.fleet.agent_registry import compute_citation_hallucination_rate


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _cleanup_task_sync(task_id: int) -> None:
    async def _run() -> None:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(AgentRun).where(AgentRun.task_id == task_id)
                )
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _make_task_sync() -> int:
    async def _run() -> int:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                task = DevTask(
                    title="t443 hallucination", description="d", status="pending"
                )
                session.add(task)
                await session.commit()
                return task.id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


class TestFinishAgentRunPersistsCitationHallucinationCount:
    def test_success_path_persists_the_real_count(self) -> None:
        task_id = _make_task_sync()
        try:

            async def _run() -> AgentRun:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        run = await create_agent_run(
                            session, task_id, "bug_fix", "claude-test-model"
                        )
                        await finish_agent_run(
                            session,
                            run.id,
                            "completed",
                            citation_hallucination_count=2,
                        )
                        refreshed = await session.get(AgentRun, run.id)
                        assert refreshed is not None
                        return refreshed
                finally:
                    await engine.dispose()

            row = asyncio.run(_run())
            assert row.citation_hallucination_count == 2
        finally:
            _cleanup_task_sync(task_id)

    def test_failure_path_leaves_the_column_null(self) -> None:
        task_id = _make_task_sync()
        try:

            async def _run() -> AgentRun:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        run = await create_agent_run(
                            session, task_id, "bug_fix", "claude-test-model"
                        )
                        await finish_agent_run(session, run.id, "failed", error="boom")
                        refreshed = await session.get(AgentRun, run.id)
                        assert refreshed is not None
                        return refreshed
                finally:
                    await engine.dispose()

            row = asyncio.run(_run())
            assert row.citation_hallucination_count is None
        finally:
            _cleanup_task_sync(task_id)


class TestComputeCitationHallucinationRate:
    def test_no_data_returns_none_not_a_fabricated_zero(self) -> None:
        async def _run() -> tuple[float | None, int]:
            engine = _engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                    return await compute_citation_hallucination_rate(
                        db, "totally-unused-agent-type-t443"
                    )
            finally:
                await engine.dispose()

        rate, sample_size = asyncio.run(_run())
        assert rate is None
        assert sample_size == 0

    def test_real_fraction_of_flagged_runs(self) -> None:
        task_id = _make_task_sync()
        agent_type = "t443-hallucination-fraction-test"
        try:

            async def _run() -> tuple[float | None, int]:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        # 3 runs: 2 flagged (count > 0), 1 clean (count == 0)
                        for count in (1, 3, 0):
                            run = await create_agent_run(
                                session, task_id, agent_type, "claude-test-model"
                            )
                            await finish_agent_run(
                                session,
                                run.id,
                                "completed",
                                citation_hallucination_count=count,
                            )
                        return await compute_citation_hallucination_rate(
                            session, agent_type
                        )
                finally:
                    await engine.dispose()

            rate, sample_size = asyncio.run(_run())
            assert sample_size == 3
            assert rate == pytest.approx(2 / 3)
        finally:
            _cleanup_task_sync(task_id)

    def test_runs_with_null_count_are_excluded_from_the_denominator(self) -> None:
        """A run that crashed before the graph finished (NULL, never 0) must
        not silently count as 'clean' — it has no real signal either way."""
        task_id = _make_task_sync()
        agent_type = "t443-null-exclusion-test"
        try:

            async def _run() -> tuple[float | None, int]:
                engine = _engine()
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        flagged_run = await create_agent_run(
                            session, task_id, agent_type, "claude-test-model"
                        )
                        await finish_agent_run(
                            session,
                            flagged_run.id,
                            "completed",
                            citation_hallucination_count=1,
                        )
                        crashed_run = await create_agent_run(
                            session, task_id, agent_type, "claude-test-model"
                        )
                        await finish_agent_run(
                            session, crashed_run.id, "failed", error="crashed"
                        )
                        return await compute_citation_hallucination_rate(
                            session, agent_type
                        )
                finally:
                    await engine.dispose()

            rate, sample_size = asyncio.run(_run())
            assert sample_size == 1
            assert rate == pytest.approx(1.0)
        finally:
            _cleanup_task_sync(task_id)
