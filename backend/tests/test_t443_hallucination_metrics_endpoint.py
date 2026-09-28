"""#443 (2026-09-28) — GET /api/agents/{name}/metrics now surfaces a real
hallucinationFlagRate/hallucinationSampleSize, computed from AgentRun.
citation_hallucination_count (see app.fleet.agent_registry.
compute_citation_hallucination_rate). Real TestClient + real Postgres,
mirroring test_t2b3_avg_retries_persisted.py's own established convention.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.db.models import AgentRun, DevTask
from app.main import app


def _cleanup(agent_name: str, task_id: int | None) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import Agent

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(delete(Agent).where(Agent.name == agent_name))
                await session.execute(
                    delete(AgentRun).where(AgentRun.agent_type == agent_name)
                )
                if task_id is not None:
                    await session.execute(
                        delete(DevTask).where(DevTask.id == task_id)
                    )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _make_task_sync() -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings

    async def _run() -> int:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                task = DevTask(
                    title="t443 endpoint test", description="d", status="pending"
                )
                session.add(task)
                await session.commit()
                return task.id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_metrics_endpoint_surfaces_real_hallucination_rate() -> None:
    from app.db.repository import create_agent_run, finish_agent_run

    agent_name = "td-t443-hallucination-metrics-agent"
    task_id = _make_task_sync()
    try:
        with TestClient(app) as client:
            reg_resp = client.post(
                "/api/agents",
                json={
                    "name": agent_name,
                    "capability_tags": ["testing"],
                    "tool_list": [],
                },
            )
            assert reg_resp.status_code == 200, reg_resp.text

            async def _seed() -> None:
                from sqlalchemy.ext.asyncio import (
                    async_sessionmaker,
                    create_async_engine,
                )

                from app.config import get_settings

                engine = create_async_engine(
                    get_settings().database_url, pool_pre_ping=True
                )
                try:
                    async with async_sessionmaker(
                        engine, expire_on_commit=False
                    )() as session:
                        for count in (1, 0):
                            run = await create_agent_run(
                                session, task_id, agent_name, "claude-test-model"
                            )
                            await finish_agent_run(
                                session,
                                run.id,
                                "completed",
                                citation_hallucination_count=count,
                            )
                finally:
                    await engine.dispose()

            asyncio.run(_seed())

            resp = client.get(f"/api/agents/{agent_name}/metrics")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["hallucinationFlagRate"] == 0.5
            assert body["hallucinationSampleSize"] == 2
    finally:
        _cleanup(agent_name, task_id)


def test_metrics_endpoint_reports_none_with_no_hallucination_data() -> None:
    agent_name = "td-t443-hallucination-no-data-agent"
    with TestClient(app) as client:
        reg_resp = client.post(
            "/api/agents",
            json={"name": agent_name, "capability_tags": ["testing"], "tool_list": []},
        )
        assert reg_resp.status_code == 200, reg_resp.text
        try:
            resp = client.get(f"/api/agents/{agent_name}/metrics")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["hallucinationFlagRate"] is None
            assert body["hallucinationSampleSize"] == 0
        finally:
            _cleanup(agent_name, None)
