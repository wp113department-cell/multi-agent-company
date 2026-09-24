"""T2-B7 (2026-09-24, GRIDIRON_PARTIAL #407 "Per-agent performance metrics
aggregated over time (persisted, not just ring buffer)").

app/fleet/metrics.py::RunMetrics already computed retries/verification_pct/
confidence/tool_accuracy/cost_estimate_usd per run, but none of it ever
reached a durable table — only the in-process MetricsCollector ring buffer
(lost on restart). Migration 057 adds the missing AgentRun columns;
finish_agent_run(_sync) now persists them; GET /api/metrics's per-agent-type
breakdown now surfaces real historical averages computed from AgentRun
itself, not the ring buffer. Real Postgres + real TestClient, no mocks.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import AgentRun, DevTask
from app.db.repository import create_agent_run, finish_agent_run
from app.main import app
from app.middleware.rbac import require_authenticated


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _cleanup_task_sync(task_id: int) -> None:
    async def _run() -> None:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(delete(AgentRun).where(AgentRun.task_id == task_id))
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
                task = DevTask(title="t2b7 metrics", description="d", status="pending")
                session.add(task)
                await session.commit()
                return task.id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


class TestFinishAgentRunPersistsPerformanceMetrics:
    def test_success_path_persists_all_four_new_columns(self) -> None:
        task_id = _make_task_sync()
        try:

            async def _run() -> AgentRun:
                engine = _engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                        run = await create_agent_run(
                            session, task_id, "bug_fix", "claude-test-model"
                        )
                        await finish_agent_run(
                            session,
                            run.id,
                            "completed",
                            tokens_in=100,
                            tokens_out=50,
                            cost_estimate=0.0123,
                            retries=2,
                            verification_pct=0.75,
                            confidence=0.9,
                            tool_accuracy=0.8,
                        )
                        refreshed = await session.get(AgentRun, run.id)
                        assert refreshed is not None
                        return refreshed
                finally:
                    await engine.dispose()

            row = asyncio.run(_run())
            assert row.retries == 2
            assert row.verification_pct == pytest.approx(0.75)
            assert row.confidence == pytest.approx(0.9)
            assert row.tool_accuracy == pytest.approx(0.8)
            assert float(row.cost_estimate) == pytest.approx(0.0123)
        finally:
            _cleanup_task_sync(task_id)

    def test_failure_path_with_no_metrics_leaves_new_columns_null(self) -> None:
        # Mirrors base_graph.py's own exception-path call site: only
        # status + error are known, never fabricated defaults for fields
        # that were never genuinely computed for a run that crashed before
        # reaching them.
        task_id = _make_task_sync()
        try:

            async def _run() -> AgentRun:
                engine = _engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                        run = await create_agent_run(
                            session, task_id, "bug_fix", "claude-test-model"
                        )
                        await finish_agent_run(
                            session, run.id, "failed", error="boom"
                        )
                        refreshed = await session.get(AgentRun, run.id)
                        assert refreshed is not None
                        return refreshed
                finally:
                    await engine.dispose()

            row = asyncio.run(_run())
            assert row.status == "failed"
            assert row.retries is None
            assert row.verification_pct is None
            assert row.confidence is None
            assert row.tool_accuracy is None
        finally:
            _cleanup_task_sync(task_id)


@pytest.fixture
def client():
    actor = f"t2b7-user-{uuid.uuid4().hex[:8]}"
    app.dependency_overrides[require_authenticated] = lambda: actor
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(require_authenticated, None)


class TestMetricsEndpointSurfacesRealAverages:
    def test_agent_type_breakdown_includes_real_historical_averages(
        self, client: TestClient
    ) -> None:
        task_id = _make_task_sync()
        agent_type = f"t2b7-agent-{uuid.uuid4().hex[:8]}"
        try:

            async def _seed() -> None:
                engine = _engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                        r1 = await create_agent_run(session, task_id, agent_type, "m")
                        await finish_agent_run(
                            session,
                            r1.id,
                            "completed",
                            tokens_in=10,
                            tokens_out=5,
                            cost_estimate=1.0,
                            retries=0,
                            verification_pct=1.0,
                            confidence=1.0,
                            tool_accuracy=1.0,
                        )
                        r2 = await create_agent_run(session, task_id, agent_type, "m")
                        await finish_agent_run(
                            session,
                            r2.id,
                            "completed",
                            tokens_in=10,
                            tokens_out=5,
                            cost_estimate=2.0,
                            retries=2,
                            verification_pct=0.5,
                            confidence=0.6,
                            tool_accuracy=0.4,
                        )
                finally:
                    await engine.dispose()

            asyncio.run(_seed())

            resp = client.get("/api/metrics")
            assert resp.status_code == 200
            breakdown = {
                row["agentType"]: row for row in resp.json()["agentTypeBreakdown"]
            }
            assert agent_type in breakdown
            row = breakdown[agent_type]
            assert row["avgRetries"] == pytest.approx(1.0)
            assert row["avgVerificationPct"] == pytest.approx(0.75)
            assert row["avgConfidence"] == pytest.approx(0.8)
            assert row["avgToolAccuracy"] == pytest.approx(0.7)
            assert row["totalCostEstimate"] == pytest.approx(3.0)
        finally:
            _cleanup_task_sync(task_id)
