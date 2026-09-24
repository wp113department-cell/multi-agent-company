"""T2-B3 (2026-09-22, GRIDIRON_PARTIAL #437 "Retry count (real per-run
persisted value)").

Before this, Agent.avg_retries was read at GET /api/agents/{name}/metrics
but never written by anything in the codebase — confirmed by repo search —
so it stayed at its 0.0 default forever, and the endpoint's own comment
("approximated from tokens") described an approximation that didn't
actually exist in code. RunMetrics.retries (the real per-run value,
base_graph.py's run_agent_graph()) was already being set correctly; nothing
ever aggregated it back into the durable column.

Matches tests/test_batch16_scheduler_and_metrics.py's own real-TestClient +
real-collector convention (registered directly on MetricsCollector, no
mocking, since MetricsCollector is the actual real source of truth this
endpoint reads).
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app


def _cleanup_agent(name: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import Agent

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(delete(Agent).where(Agent.name == name))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _get_persisted_avg_retries(name: str) -> float | None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import Agent

    async def _run() -> float | None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await session.execute(
                    select(Agent.avg_retries).where(Agent.name == name)
                )
                return result.scalar_one_or_none()
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_avg_retries_reflects_real_per_run_retries_and_is_persisted() -> None:
    from app.fleet.metrics import get_metrics_collector

    agent_name = "td-t2b3-avg-retries-agent"
    with TestClient(app) as client:
        reg_resp = client.post(
            "/api/agents",
            json={"name": agent_name, "capability_tags": ["testing"], "tool_list": []},
        )
        assert reg_resp.status_code == 200, reg_resp.text
        try:
            collector = get_metrics_collector()
            run1 = collector.start_run(agent_name)
            run1.retries = 2
            run2 = collector.start_run(agent_name)
            run2.retries = 0

            resp = client.get(f"/api/agents/{agent_name}/metrics")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["avgRetries"] == 1.0  # (2 + 0) / 2

            # The real point of #437: this must be a DURABLE write, not
            # just an in-request computation — a fresh read straight from
            # Postgres (bypassing the in-process collector entirely) must
            # see it too.
            persisted = _get_persisted_avg_retries(agent_name)
            assert persisted == 1.0
        finally:
            _cleanup_agent(agent_name)


def test_avg_retries_falls_back_to_persisted_value_with_no_ring_buffer_history() -> (
    None
):
    """A fresh agent with no MetricsCollector history yet must not report a
    fabricated 0.0 as if it were a real measurement — falls back to
    whatever's already durably stored (0.0 for a brand-new agent, same as
    today's default)."""
    agent_name = "td-t2b3-avg-retries-agent-fresh"
    with TestClient(app) as client:
        reg_resp = client.post(
            "/api/agents",
            json={"name": agent_name, "capability_tags": ["testing"], "tool_list": []},
        )
        assert reg_resp.status_code == 200, reg_resp.text
        try:
            resp = client.get(f"/api/agents/{agent_name}/metrics")
            assert resp.status_code == 200, resp.text
            assert resp.json()["avgRetries"] == 0.0
        finally:
            _cleanup_agent(agent_name)
