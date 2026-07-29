"""Real-DB tests for MASTER_AGENT_v2.md Phase 6.2 — read-only reporting
endpoints (cost, fleet health, repair patterns) on app/api/fleet_dashboard.py.

Seeds real agent_runs / memory_embeddings rows via app.db.repository's real
helpers (same real-DB convention as tests/test_orphan_recovery.py) and
asserts on the actual response from a real running FastAPI app hitting a
real database — not mocked aggregation logic, per the spec's own DoD
("reporting endpoints tested against seeded agent_runs rows with known
values"). Every seeded agent/summary name is namespaced with a per-test
uuid marker so assertions never depend on the table being otherwise empty.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.fleet_dashboard import router
from app.db.repository import create_agent_run, create_task
from app.db.session import get_db


def _new_isolated_db_engine() -> Any:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _seed() -> dict[str, Any]:
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentRun, MemoryEmbedding

    marker = uuid.uuid4().hex[:8]
    agent_a = f"td_report_agent_a_{marker}"
    agent_b = f"td_report_agent_b_{marker}"
    pattern = f"td repair pattern {marker}"

    async def _run() -> dict[str, Any]:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                task = await create_task(session, "td reporting task", "desc")

                run1 = await create_agent_run(
                    session, task.id, agent_a, "claude-opus-4"
                )
                run2 = await create_agent_run(
                    session, task.id, agent_a, "claude-opus-4"
                )
                run3 = await create_agent_run(
                    session, task.id, agent_b, "claude-haiku-4"
                )

                await session.execute(
                    update(AgentRun)
                    .where(AgentRun.id == run1.id)
                    .values(
                        status="completed",
                        tokens_in=1000,
                        tokens_out=200,
                        cost_estimate=0.05,
                    )
                )
                await session.execute(
                    update(AgentRun)
                    .where(AgentRun.id == run2.id)
                    .values(
                        status="failed",
                        tokens_in=500,
                        tokens_out=100,
                        cost_estimate=0.02,
                    )
                )
                # Real UTC, tz-aware — matches app/db/repository.py's real
                # heartbeat_agent_run() write path exactly (unlike
                # test_orphan_recovery.py's naive convention, which only
                # works there because it's a threshold *comparison*, not an
                # absolute-seconds value like this test needs).
                stale_hb = datetime.now(timezone.utc) - timedelta(seconds=1200)
                await session.execute(
                    update(AgentRun)
                    .where(AgentRun.id == run3.id)
                    .values(
                        status="running",
                        tokens_in=10,
                        tokens_out=5,
                        cost_estimate=0.001,
                        last_heartbeat_at=stale_hb,
                    )
                )

                session.add_all(
                    [
                        MemoryEmbedding(
                            task_id=f"td-{marker}-1",
                            outcome="failure",
                            category="failure",
                            description="err1",
                            summary=pattern,
                            files_changed=[],
                            archived=False,
                        ),
                        MemoryEmbedding(
                            task_id=f"td-{marker}-2",
                            outcome="failure",
                            category="failure",
                            description="err2",
                            summary=pattern,
                            files_changed=[],
                            archived=False,
                        ),
                    ]
                )
                await session.commit()
                return {
                    "task_id": task.id,
                    "agent_a": agent_a,
                    "agent_b": agent_b,
                    "pattern": pattern,
                    "marker": marker,
                }
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


def _cleanup(task_id: int, pattern: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask, MemoryEmbedding

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                await session.execute(
                    delete(MemoryEmbedding).where(MemoryEmbedding.summary == pattern)
                )
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def _client() -> TestClient:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    app = FastAPI()
    app.include_router(router)

    async def _override() -> Any:
        engine = _new_isolated_db_engine()
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
            yield session
        await engine.dispose()  # type: ignore[attr-defined]

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def test_cost_report_aggregates_real_agent_runs() -> None:
    seed = _seed()
    try:
        with _client() as client:
            resp = client.get("/api/fleet/reports/cost", params={"days": 365})
        assert resp.status_code == 200
        data = resp.json()

        rows = [r for r in data["byAgentDay"] if r["agentName"] == seed["agent_a"]]
        assert len(rows) == 1
        row = rows[0]
        assert row["tokensIn"] == 1500
        assert row["tokensOut"] == 300
        assert abs(row["costUsd"] - 0.07) < 1e-6
        assert row["runCount"] == 2

        b_rows = [r for r in data["byAgentDay"] if r["agentName"] == seed["agent_b"]]
        assert len(b_rows) == 1
        assert b_rows[0]["tokensIn"] == 10

        tier = row["tier"]
        tier_entry = next(t for t in data["byTier"] if t["tier"] == tier)
        assert tier_entry["costUsd"] >= 0.07
    finally:
        _cleanup(seed["task_id"], seed["pattern"])


def test_health_report_computes_real_failure_rate_and_staleness() -> None:
    seed = _seed()
    try:
        with _client() as client:
            resp = client.get("/api/fleet/reports/health")
        assert resp.status_code == 200
        data = resp.json()
        by_name = {r["agentName"]: r for r in data}

        a = by_name[seed["agent_a"]]
        assert a["totalRuns"] == 2
        assert a["failedRuns"] == 1
        assert abs(a["failureRate"] - 0.5) < 1e-6
        assert a["activeRuns"] == 0

        b = by_name[seed["agent_b"]]
        assert b["totalRuns"] == 1
        assert b["failedRuns"] == 0
        assert b["activeRuns"] == 1
        assert b["avgHeartbeatStalenessSeconds"] is not None
        assert 1100 <= b["avgHeartbeatStalenessSeconds"] <= 1400
    finally:
        _cleanup(seed["task_id"], seed["pattern"])


def test_repair_patterns_report_counts_real_occurrences() -> None:
    seed = _seed()
    try:
        with _client() as client:
            resp = client.get(
                "/api/fleet/reports/repair-patterns", params={"limit": 100}
            )
        assert resp.status_code == 200
        data = resp.json()
        entry = next(r for r in data if r["repairPattern"] == seed["pattern"])
        assert entry["occurrences"] == 2
        assert entry["lastSeen"] is not None
    finally:
        _cleanup(seed["task_id"], seed["pattern"])


def test_cost_report_days_param_is_bounded() -> None:
    with _client() as client:
        resp = client.get("/api/fleet/reports/cost", params={"days": 0})
    assert resp.status_code == 422
    with _client() as client:
        resp = client.get("/api/fleet/reports/cost", params={"days": 9999})
    assert resp.status_code == 422
