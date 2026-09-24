"""T2-B6 (2026-09-24, GRIDIRON_PARTIAL #381 "Usage analytics — full
per-user cost/token attribution").

DevTask.created_by / Epic.created_by (migrations 055/056) are populated
from the real authenticated actor at every task/epic-creating endpoint;
GET /api/metrics/users rolls AgentRun's existing cost/token columns up per
created_by. Real Postgres + real TestClient, no mocks.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import AgentRun, DevTask
from app.main import app
from app.middleware.rbac import require_approver, require_authenticated


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@pytest.fixture
def client():
    actor = f"t2b6-user-{uuid.uuid4().hex[:8]}"
    app.dependency_overrides[require_approver] = lambda: actor
    app.dependency_overrides[require_authenticated] = lambda: actor
    try:
        with TestClient(app) as c:
            yield c, actor
    finally:
        app.dependency_overrides.pop(require_approver, None)
        app.dependency_overrides.pop(require_authenticated, None)


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


def _add_agent_run_sync(
    task_id: int, cost: str, tokens_in: int, tokens_out: int
) -> None:
    async def _run() -> None:
        engine = _engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                session.add(
                    AgentRun(
                        id=str(uuid.uuid4()),
                        task_id=task_id,
                        agent_type="test_agent",
                        status="completed",
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        cost_estimate=Decimal(cost),
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


class TestCreatedByPopulatedAtCreation:
    def test_post_task_records_the_authenticated_actor(self, client) -> None:
        c, actor = client
        resp = c.post(
            "/api/tasks",
            json={"title": "t2b6 attribution", "description": "d"},
        )
        assert resp.status_code == 201
        task_id = resp.json()["id"]
        try:
            assert resp.json()["createdBy"] == actor

            got = c.get(f"/api/tasks/{task_id}")
            assert got.json()["createdBy"] == actor
        finally:
            _cleanup_task_sync(task_id)

    def test_repeat_task_records_the_repeating_actor_not_the_original(
        self, client
    ) -> None:
        c, actor = client
        original = c.post(
            "/api/tasks",
            json={"title": "t2b6 original", "description": "d"},
        ).json()
        original_id = original["id"]

        # Repeat as a DIFFERENT actor than the one who created the original.
        second_actor = f"t2b6-user-{uuid.uuid4().hex[:8]}"
        app.dependency_overrides[require_approver] = lambda: second_actor
        try:
            repeated = c.post(f"/api/tasks/{original_id}/repeat", json={})
        finally:
            app.dependency_overrides[require_approver] = lambda: actor
        assert repeated.status_code == 201
        repeated_task = repeated.json()["task"]
        repeated_id = repeated_task["id"]
        try:
            assert repeated_task["createdBy"] == second_actor
            assert original["createdBy"] == actor
        finally:
            _cleanup_task_sync(original_id)
            _cleanup_task_sync(repeated_id)


class TestUserUsageRollup:
    def test_rollup_aggregates_cost_and_tokens_for_the_real_actor(self, client) -> None:
        c, actor = client
        task_id = c.post(
            "/api/tasks",
            json={"title": "t2b6 rollup", "description": "d"},
        ).json()["id"]
        try:
            _add_agent_run_sync(task_id, "1.500000", 1000, 500)
            _add_agent_run_sync(task_id, "0.250000", 200, 100)

            resp = c.get("/api/metrics/users")
            assert resp.status_code == 200
            rows = {r["createdBy"]: r for r in resp.json()}
            assert actor in rows
            row = rows[actor]
            assert row["taskCount"] == 1
            assert row["runCount"] == 2
            assert row["totalTokensIn"] == 1200
            assert row["totalTokensOut"] == 600
            assert row["totalCostEstimate"] == pytest.approx(1.75)
        finally:
            _cleanup_task_sync(task_id)

    def test_actor_with_no_agent_runs_is_absent_from_the_rollup(self, client) -> None:
        c, actor = client
        task_id = c.post(
            "/api/tasks",
            json={"title": "t2b6 no runs yet", "description": "d"},
        ).json()["id"]
        try:
            resp = c.get("/api/metrics/users")
            rows = {r["createdBy"]: r for r in resp.json()}
            assert actor not in rows
        finally:
            _cleanup_task_sync(task_id)
