"""Gap-closure (files/GAPS_ALL_FILES_REPORT.md, 2026-07-23) — dev_tasks was
missing real priority/assigned_agent/project/final_summary columns;
_task_to_dict() faked them as hardcoded placeholder values
("priority": "medium", "assignedAgent": None, "project": None,
"finalSummary": None). Verifies the real migration-018 columns round-trip
through create_task()/GET, and that assigned_agent/final_summary are set at
real dispatch/completion points, not just schema-present.

launch_manager()'s "manager" assignment is NOT tested end-to-end here,
matching this codebase's own established precedent
(test_launch_manager_push_approval.py's docstring): launch_manager() is
reached via a raw asyncio.create_task() fire-and-forget nested inside
resume_planning_pipeline() (itself a background task) — not a single-level
BackgroundTasks dispatch like launch_coder()/launch_planning_pipeline(), so
driving it through TestClient to completion is brittle. That call site was
added directly alongside the existing, already-tested worktree/pipeline-state
setup at the top of launch_manager() — confirmed by reading the code, the
same standard this codebase already applies to that function.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _get_task(task_id: int) -> object:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask

    async def _run() -> object:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                task = await session.get(DevTask, task_id)
                assert task is not None
                return task
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


def _set_status_and_plan(task_id: int, status: str, plan: str = "") -> None:
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(
                    update(DevTask)
                    .where(DevTask.id == task_id)
                    .values(status=status, plan=plan)
                )
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def _cleanup(task_id: int) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


class TestCreateTaskWithMetadata:
    def test_priority_and_project_round_trip_through_create_and_get(self) -> None:
        with TestClient(app) as client:
            resp = client.post(
                "/api/tasks",
                json={
                    "title": "td metadata task",
                    "description": "desc",
                    "priority": "high",
                    "project": "gridiron-web",
                },
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            task_id = body["id"]
            try:
                assert body["priority"] == "high"
                assert body["project"] == "gridiron-web"
                # Nothing has dispatched yet — these are real defaults, not
                # the old hardcoded-None placeholders.
                assert body["assignedAgent"] is None
                assert body["finalSummary"] is None

                get_resp = client.get(f"/api/tasks/{task_id}")
                assert get_resp.status_code == 200
                get_body = get_resp.json()
                assert get_body["priority"] == "high"
                assert get_body["project"] == "gridiron-web"
            finally:
                _cleanup(task_id)

    def test_priority_defaults_to_medium_when_omitted(self) -> None:
        with TestClient(app) as client:
            resp = client.post(
                "/api/tasks", json={"title": "td default priority", "description": "d"}
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            task_id = body["id"]
            try:
                assert body["priority"] == "medium"
                assert body["project"] is None
            finally:
                _cleanup(task_id)


class TestAssignedAgentAndFinalSummaryWiring:
    """Real dispatch-path wiring, not just schema presence — driven through a
    real TestClient (safe here: /run and /approve both use a single-level
    BackgroundTasks.add_task(), unlike launch_manager()'s fire-and-forget
    nesting — see this file's module docstring)."""

    def test_launch_coder_sets_assigned_agent_and_final_summary(self) -> None:
        with TestClient(app) as client:
            resp = client.post(
                "/api/tasks",
                json={"title": "td coder wiring", "description": "d"},
            )
            task_id = resp.json()["id"]
            _set_status_and_plan(task_id, "ready_for_review", "Do the thing.")
            try:
                with patch(
                    "app.agents.coder.run_coder",
                    return_value=(["app/foo.py"], None, 10, 10),
                ), patch(
                    "app.api.agents.create_worktree", return_value="/tmp/td-wt"
                ), patch(
                    "app.api.agents.get_diff", return_value="diff --git a/foo b/foo"
                ), patch(
                    "app.api.agents.preserve_worktree"
                ):
                    approve_resp = client.post(f"/api/tasks/{task_id}/approve")
                assert approve_resp.status_code == 200, approve_resp.text

                task = _get_task(task_id)
                assert task.assigned_agent == "coder"  # type: ignore[attr-defined]
                assert task.final_summary is not None  # type: ignore[attr-defined]
                assert "1 files changed" in task.final_summary  # type: ignore[attr-defined]
            finally:
                _cleanup(task_id)

    def test_launch_planning_pipeline_sets_assigned_agent_to_pm(self) -> None:
        """/run (mode=full) dispatches launch_planning_pipeline() directly via
        a single-level BackgroundTasks.add_task() — safely TestClient-
        testable. Mocks run_planning_pipeline (the LangGraph call) so this
        needs no real LLM key; only the assigned_agent write (set before the
        mocked pipeline call even runs) is under test here."""
        with TestClient(app) as client:
            resp = client.post(
                "/api/tasks", json={"title": "td pm wiring", "description": "d"}
            )
            task_id = resp.json()["id"]
            try:
                with patch(
                    "app.pipeline.graph.run_planning_pipeline",
                    return_value={"stage": "blocked", "error": "stubbed for this test"},
                ):
                    run_resp = client.post(
                        f"/api/tasks/{task_id}/run", json={"mode": "full"}
                    )
                assert run_resp.status_code == 200, run_resp.text

                task = _get_task(task_id)
                assert task.assigned_agent == "pm"  # type: ignore[attr-defined]
            finally:
                _cleanup(task_id)

    def test_launch_planner_sets_assigned_agent_to_planner(self) -> None:
        with TestClient(app) as client:
            resp = client.post(
                "/api/tasks", json={"title": "td planner wiring", "description": "d"}
            )
            task_id = resp.json()["id"]
            try:
                with patch(
                    "app.agents.planner.run_planner",
                    return_value=("A plan.", None, 5, 5),
                ):
                    run_resp = client.post(
                        f"/api/tasks/{task_id}/run", json={"mode": "simple"}
                    )
                assert run_resp.status_code == 200, run_resp.text

                task = _get_task(task_id)
                assert task.assigned_agent == "planner"  # type: ignore[attr-defined]
            finally:
                _cleanup(task_id)
