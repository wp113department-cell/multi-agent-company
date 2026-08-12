"""AUDIT_Q_BATCH18 §51 gap-closure (2026-08-12) — "Repeat Task & Historical
Context" was PARTIAL: only implicit semantic-similarity recall
(memory_hook_node) existed, with no way to say "the same one as yesterday"
and have it resolved deterministically. Proves the new deterministic path:
db.repository.repeat_task() + POST /api/tasks/{task_id}/repeat.

Follows test_audit04_orchestration_fixes.py's established pattern:
isolated engine for setup/teardown, real TestClient so BackgroundTasks
execute synchronously, launch_planning_pipeline/launch_planner mocked at
their definition site (app.api.agents) since every real caller does a
deferred import.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _cleanup_task(task_id: int) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask, Subtask

    async def _do() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(delete(Subtask).where(Subtask.task_id == task_id))
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    _run(_do())


def _create_task_with_status(status: str, priority: str = "medium") -> int:
    from sqlalchemy import update

    from app.db.models import DevTask
    from app.db.repository import create_task

    async def _do() -> int:
        engine = _new_isolated_db_engine()
        try:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                task = await create_task(
                    session,
                    "batch18 repeat test task",
                    "original description",
                    priority=priority,
                )
                await session.execute(
                    update(DevTask).where(DevTask.id == task.id).values(status=status)
                )
                await session.commit()
                return task.id
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return _run(_do())


def _get_task_row(task_id: int):  # type: ignore[no-untyped-def]
    from app.db.models import DevTask
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async def _do():  # type: ignore[no-untyped-def]
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                return await session.get(DevTask, task_id)
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return _run(_do())


class TestRepeatTaskRepository:
    def test_repeat_task_clones_fields_and_sets_reference(self) -> None:
        from app.db.repository import repeat_task
        from sqlalchemy.ext.asyncio import async_sessionmaker

        async def _do() -> tuple[int, int]:
            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    from app.db.repository import create_task

                    source = await create_task(
                        session,
                        "source title",
                        "source description",
                        priority="high",
                    )
                    new_task = await repeat_task(session, source)
                    return source.id, new_task.id
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        source_id, new_id = _run(_do())
        try:
            new_row = _get_task_row(new_id)
            assert new_row is not None
            assert new_row.title == "source title"
            assert new_row.description == "source description"
            assert new_row.priority == "high"
            assert new_row.status == "pending"
            assert new_row.repeated_from_task_id == source_id
        finally:
            _cleanup_task(new_id)
            _cleanup_task(source_id)

    def test_repeat_task_allows_overrides(self) -> None:
        from app.db.repository import repeat_task
        from sqlalchemy.ext.asyncio import async_sessionmaker

        async def _do() -> tuple[int, int]:
            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    from app.db.repository import create_task

                    source = await create_task(
                        session, "source title", "source description"
                    )
                    new_task = await repeat_task(
                        session,
                        source,
                        title="overridden title",
                        priority="low",
                    )
                    return source.id, new_task.id
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        source_id, new_id = _run(_do())
        try:
            new_row = _get_task_row(new_id)
            assert new_row.title == "overridden title"
            assert new_row.description == "source description"  # not overridden
            assert new_row.priority == "low"
        finally:
            _cleanup_task(new_id)
            _cleanup_task(source_id)


class TestRepeatTaskEndpoint:
    def test_repeat_completed_task_creates_and_dispatches_new_task(self) -> None:
        source_id = _create_task_with_status("completed")
        try:
            with patch("app.api.agents.launch_planning_pipeline") as mock_launch:
                with TestClient(app) as client:
                    resp = client.post(f"/api/tasks/{source_id}/repeat", json={})
                assert resp.status_code == 201, resp.text
                body = resp.json()
                assert body["repeated"] is True
                assert body["sourceTaskId"] == source_id
                new_id = body["taskId"]
                assert new_id != source_id
                assert body["task"]["repeatedFromTaskId"] == source_id
                assert body["task"]["status"] == "planning"
            mock_launch.assert_called_once()
        finally:
            _cleanup_task(body["taskId"])
            _cleanup_task(source_id)

    def test_repeat_with_overrides(self) -> None:
        source_id = _create_task_with_status("failed")
        try:
            with patch("app.api.agents.launch_planning_pipeline"):
                with TestClient(app) as client:
                    resp = client.post(
                        f"/api/tasks/{source_id}/repeat",
                        json={"title": "a different attempt", "priority": "high"},
                    )
                assert resp.status_code == 201, resp.text
                body = resp.json()
                assert body["task"]["title"] == "a different attempt"
                assert body["task"]["priority"] == "high"
                assert body["task"]["description"] == "original description"
        finally:
            _cleanup_task(body["taskId"])
            _cleanup_task(source_id)

    def test_repeat_nonexistent_task_404s(self) -> None:
        with TestClient(app) as client:
            resp = client.post("/api/tasks/999999999/repeat", json={})
        assert resp.status_code == 404
