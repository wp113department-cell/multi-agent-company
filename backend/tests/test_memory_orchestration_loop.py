"""plan14 #14 — Memory + Orchestration as One Feedback System.

Not a separate build (per the plan's own framing): the write side
(app.memory.hooks -> app.memory.store) already existed; follow-on #3 added
the read side (FleetManager.select() querying AgentHistoricalPerformance,
itself a rollup over memory_embeddings.agent_name). This is the last piece
— making that closed loop actually VISIBLE to a human, via a real read-only
reporting endpoint on the existing fleet dashboard (GET /api/fleet/reports/
agent-memory-performance), tested against real seeded rows the same way
every other report endpoint in tests/test_phase62_reporting_endpoints.py
already is.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.fleet_dashboard import router
from app.db.session import get_db


def _new_isolated_db_engine() -> Any:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _seed() -> dict[str, Any]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentHistoricalPerformance

    marker = uuid.uuid4().hex[:8]
    agent_name = f"td_ahp_report_agent_{marker}"

    async def _run() -> dict[str, Any]:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                session.add_all(
                    [
                        AgentHistoricalPerformance(
                            agent_name=agent_name,
                            category="task",
                            sample_size=12,
                            success_rate=0.75,
                            avg_importance=0.6,
                            verified_rate=0.3,
                        ),
                        AgentHistoricalPerformance(
                            agent_name=agent_name,
                            category="architecture",
                            sample_size=5,
                            success_rate=None,
                            avg_importance=0.5,
                            verified_rate=0.0,
                        ),
                    ]
                )
                await session.commit()
                return {"agent_name": agent_name, "marker": marker}
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _cleanup(agent_name: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import AgentHistoricalPerformance

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    delete(AgentHistoricalPerformance).where(
                        AgentHistoricalPerformance.agent_name == agent_name
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _client() -> TestClient:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    app = FastAPI()
    app.include_router(router)

    async def _override() -> Any:
        engine = _new_isolated_db_engine()
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
        await engine.dispose()

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def test_agent_memory_performance_report_returns_real_seeded_rows() -> None:
    seed = _seed()
    try:
        with _client() as client:
            resp = client.get("/api/fleet/reports/agent-memory-performance")
        assert resp.status_code == 200
        data = resp.json()
        rows = [r for r in data if r["agentName"] == seed["agent_name"]]
        assert len(rows) == 2

        task_row = next(r for r in rows if r["category"] == "task")
        assert task_row["sampleSize"] == 12
        assert abs(task_row["successRate"] - 0.75) < 1e-6
        assert abs(task_row["avgImportance"] - 0.6) < 1e-6
        assert abs(task_row["verifiedRate"] - 0.3) < 1e-6
        assert task_row["computedAt"] is not None

        arch_row = next(r for r in rows if r["category"] == "architecture")
        assert arch_row["successRate"] is None, (
            "architecture rows must never fabricate a success_rate — see "
            "AgentHistoricalPerformance's own docstring"
        )
        assert arch_row["sampleSize"] == 5
    finally:
        _cleanup(seed["agent_name"])


def test_agent_memory_performance_report_empty_is_not_an_error() -> None:
    """No rollup has ever run for this fresh table state (a real, expected
    condition — see agent_historical_performance's own 'neutral until real
    history exists' design) — must return 200 with an empty/unaffected list,
    never a 500."""
    with _client() as client:
        resp = client.get("/api/fleet/reports/agent-memory-performance")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
