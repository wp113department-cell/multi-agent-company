"""AUDIT_Q_BATCH16_GOVERNANCE_OPS.md gap-closure (2026-08-11).

§86 "Reorder" (PATCH /{task_id}/priority) and "Detect dependencies /
optimize order" (DevTask.depends_on gate on /run) — both real, additive API
surface with no prior test coverage. §87's registry.py metrics extension is
covered separately by direct collector assertions (no HTTP round trip
needed — the endpoint is a thin pass-through over already-tested
MetricsCollector methods).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _set_status(task_id: int, status: str) -> None:
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(
                    update(DevTask).where(DevTask.id == task_id).values(status=status)
                )
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def _cleanup(*task_ids: int) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                for tid in task_ids:
                    await session.execute(delete(DevTask).where(DevTask.id == tid))
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


class TestPatchPriority:
    def test_updates_priority_and_logs_it(self) -> None:
        with TestClient(app) as client:
            resp = client.post(
                "/api/tasks",
                json={"title": "td priority patch", "description": "d"},
            )
            assert resp.status_code == 201, resp.text
            task_id = resp.json()["id"]
            try:
                assert resp.json()["priority"] == "medium"

                patch_resp = client.patch(
                    f"/api/tasks/{task_id}/priority", json={"priority": "high"}
                )
                assert patch_resp.status_code == 200, patch_resp.text
                assert patch_resp.json()["priority"] == "high"

                get_resp = client.get(f"/api/tasks/{task_id}")
                assert get_resp.json()["priority"] == "high"

                logs_resp = client.get(f"/api/tasks/{task_id}/logs")
                categories = [lg["category"] for lg in logs_resp.json()["logs"]]
                assert "priority" in categories
            finally:
                _cleanup(task_id)

    def test_refuses_on_terminal_task(self) -> None:
        with TestClient(app) as client:
            resp = client.post(
                "/api/tasks",
                json={"title": "td priority terminal", "description": "d"},
            )
            task_id = resp.json()["id"]
            try:
                _set_status(task_id, "completed")
                patch_resp = client.patch(
                    f"/api/tasks/{task_id}/priority", json={"priority": "high"}
                )
                assert patch_resp.status_code == 409
            finally:
                _cleanup(task_id)

    def test_rejects_invalid_priority_value(self) -> None:
        with TestClient(app) as client:
            resp = client.post(
                "/api/tasks",
                json={"title": "td priority invalid", "description": "d"},
            )
            task_id = resp.json()["id"]
            try:
                patch_resp = client.patch(
                    f"/api/tasks/{task_id}/priority", json={"priority": "urgent"}
                )
                assert patch_resp.status_code == 422
            finally:
                _cleanup(task_id)


def _cleanup_agent(name: str) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import Agent

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(delete(Agent).where(Agent.name == name))
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


class TestAgentMetricsExtension:
    """AUDIT_Q_BATCH16 §87 gap-closure (2026-08-11) — p50/p95 latency and
    avg tool accuracy were real (MetricsCollector, Day 10) but only
    reachable via the fleet_metrics_read agent tool, never a REST route;
    reliability_score and user_approval_rate previously had no field at
    all. All four now on GET /api/agents/{name}/metrics."""

    def test_new_fields_present_with_no_run_history(self) -> None:
        agent_name = "td-batch16-metrics-agent"
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
            try:
                resp = client.get(f"/api/agents/{agent_name}/metrics")
                assert resp.status_code == 200, resp.text
                body = resp.json()
                # No agent_runs/MetricsCollector history yet for this fresh
                # agent — "no data" is None, not a fabricated 0.0.
                assert body["p50LatencyMs"] is None
                assert body["p95LatencyMs"] is None
                assert body["avgToolAccuracy"] is None
                assert body["userApprovalRate"] is None
                # reliability_score falls back to success_rate alone when
                # there's no tool-call history to weight in.
                assert body["reliabilityScore"] == body["successRate"]
            finally:
                _cleanup_agent(agent_name)

    def test_reliability_score_blends_success_rate_and_tool_accuracy(self) -> None:
        from app.fleet.metrics import ToolCallRecord, get_metrics_collector

        agent_name = "td-batch16-metrics-agent-2"
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
            try:
                collector = get_metrics_collector()
                run = collector.start_run(agent_name)
                run.status = "completed"
                run.tool_calls.append(
                    ToolCallRecord(
                        tool_name="read_file", success=True, duration_ms=10.0
                    )
                )

                resp = client.get(f"/api/agents/{agent_name}/metrics")
                assert resp.status_code == 200, resp.text
                body = resp.json()
                assert body["avgToolAccuracy"] == 1.0
                assert body["reliabilityScore"] == round(
                    0.5 * body["successRate"] + 0.5 * 1.0, 4
                )
            finally:
                _cleanup_agent(agent_name)


class TestDependsOnGate:
    def test_run_refused_while_dependency_incomplete(self) -> None:
        with TestClient(app) as client:
            dep_resp = client.post(
                "/api/tasks", json={"title": "td dep parent", "description": "d"}
            )
            dep_id = dep_resp.json()["id"]

            child_resp = client.post(
                "/api/tasks",
                json={
                    "title": "td dep child",
                    "description": "d",
                    "depends_on": [dep_id],
                },
            )
            child_id = child_resp.json()["id"]
            try:
                assert child_resp.json()["dependsOn"] == [dep_id]

                run_resp = client.post(f"/api/tasks/{child_id}/run", json={})
                assert run_resp.status_code == 409
                assert str(dep_id) in run_resp.text
            finally:
                _cleanup(child_id, dep_id)

    def test_dependency_gate_persists_a_discoverable_blocked_state(self) -> None:
        """T2-B7 (2026-09-24, GRIDIRON_PARTIAL #428) — before this, a task
        stuck on an unmet dependency looked identical to a normal "pending"
        task in GET /api/tasks unless someone specifically retried /run and
        hit the same 409 again. Now the gate itself persists a real,
        glanceable "blocked"/"dependency" state."""
        with TestClient(app) as client:
            dep_resp = client.post(
                "/api/tasks",
                json={"title": "td dep persist parent", "description": "d"},
            )
            dep_id = dep_resp.json()["id"]

            child_resp = client.post(
                "/api/tasks",
                json={
                    "title": "td dep persist child",
                    "description": "d",
                    "depends_on": [dep_id],
                },
            )
            child_id = child_resp.json()["id"]
            try:
                run_resp = client.post(f"/api/tasks/{child_id}/run", json={})
                assert run_resp.status_code == 409

                got = client.get(f"/api/tasks/{child_id}")
                assert got.json()["status"] == "blocked"
                assert got.json()["blockedReason"] == "dependency"

                # Retrying the same still-unmet dependency again must not
                # crash on a "blocked" -> "blocked" self-transition.
                run_resp2 = client.post(f"/api/tasks/{child_id}/run", json={})
                assert run_resp2.status_code == 409
                assert (
                    client.get(f"/api/tasks/{child_id}").json()["status"] == "blocked"
                )
            finally:
                _cleanup(child_id, dep_id)

    def test_completing_the_dependency_clears_the_blocked_reason(self) -> None:
        with TestClient(app) as client:
            dep_resp = client.post(
                "/api/tasks", json={"title": "td dep clear parent", "description": "d"}
            )
            dep_id = dep_resp.json()["id"]

            child_resp = client.post(
                "/api/tasks",
                json={
                    "title": "td dep clear child",
                    "description": "d",
                    "depends_on": [dep_id],
                },
            )
            child_id = child_resp.json()["id"]
            try:
                assert (
                    client.post(f"/api/tasks/{child_id}/run", json={}).status_code
                    == 409
                )
                assert (
                    client.get(f"/api/tasks/{child_id}").json()["blockedReason"]
                    == "dependency"
                )

                _set_status(dep_id, "completed")
                with patch(
                    "app.api.agents.launch_planner", new=AsyncMock(return_value=None)
                ):
                    run_resp = client.post(
                        f"/api/tasks/{child_id}/run", json={"mode": "simple"}
                    )
                assert run_resp.status_code == 200, run_resp.text
                assert (
                    client.get(f"/api/tasks/{child_id}").json()["blockedReason"] is None
                )
            finally:
                _cleanup(child_id, dep_id)

    def test_run_allowed_once_dependency_completed(self) -> None:
        with TestClient(app) as client:
            dep_resp = client.post(
                "/api/tasks", json={"title": "td dep parent 2", "description": "d"}
            )
            dep_id = dep_resp.json()["id"]
            _set_status(dep_id, "completed")

            child_resp = client.post(
                "/api/tasks",
                json={
                    "title": "td dep child 2",
                    "description": "d",
                    "depends_on": [dep_id],
                },
            )
            child_id = child_resp.json()["id"]
            try:
                with patch(
                    "app.api.agents.launch_planner", new=AsyncMock(return_value=None)
                ):
                    run_resp = client.post(
                        f"/api/tasks/{child_id}/run", json={"mode": "simple"}
                    )
                assert run_resp.status_code == 200, run_resp.text
            finally:
                _cleanup(child_id, dep_id)
