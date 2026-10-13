"""Sol A32 (2026-10-13): every task in a project can be found, and the
status counts are for the whole project.

Before: the task page fetched the newest tasks once and filtered and
counted them in the browser, so older tasks (an old failed or blocked one)
could not be reached and the counts were wrong past one page. Now the list
is paged with a cursor, the status filter runs on the server, and
GET /api/tasks/counts returns real per-status totals.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

from app.main import app


def _db(fn):  # type: ignore[no-untyped-def]
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings

    async def _run():  # type: ignore[no-untyped-def]
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                return await fn(s)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


@pytest.fixture
def project_with_many_tasks(tmp_path: Any) -> Any:
    from app.db.models import DevTask, Project
    from app.db.repository import create_task

    async def make(s):  # type: ignore[no-untyped-def]
        p = Project(name="A32", local_path=str(tmp_path), source="local_existing")
        s.add(p)
        await s.commit()
        await s.refresh(p)
        ids = []
        for i in range(25):
            t = await create_task(s, f"a32 task {i}", "d", project_id=p.id)
            ids.append(t.id)
        # the two oldest tasks failed long ago
        await s.execute(
            update(DevTask).where(DevTask.id.in_(ids[:2])).values(status="failed")
        )
        await s.commit()
        return p.id, ids

    pid, ids = _db(make)
    yield pid, ids

    async def clean(s):  # type: ignore[no-untyped-def]
        await s.execute(delete(DevTask).where(DevTask.id.in_(ids)))
        await s.execute(delete(Project).where(Project.id == pid))
        await s.commit()

    _db(clean)


def _client() -> Any:
    from app.middleware import rbac

    app.dependency_overrides[rbac.require_authenticated] = lambda: "admin"
    return TestClient(app)


def test_paging_reaches_every_task(project_with_many_tasks: Any) -> None:
    pid, ids = project_with_many_tasks
    seen: list[int] = []
    cursor = None
    try:
        with _client() as client:
            for _ in range(5):
                q = f"/api/tasks?project_id={pid}&limit=10"
                if cursor:
                    q += f"&cursor={cursor}"
                page = client.get(q).json()
                seen += [t["id"] for t in page["tasks"]]
                cursor = page["nextCursor"]
                if cursor is None:
                    break
    finally:
        app.dependency_overrides.clear()
    assert sorted(seen) == sorted(ids)  # all 25, across three pages


def test_old_failed_tasks_are_found_by_the_status_filter(
    project_with_many_tasks: Any,
) -> None:
    pid, ids = project_with_many_tasks
    try:
        with _client() as client:
            failed = client.get(f"/api/tasks?project_id={pid}&status=failed&limit=10")
            counts = client.get(f"/api/tasks/counts?project_id={pid}").json()
    finally:
        app.dependency_overrides.clear()
    assert sorted(t["id"] for t in failed.json()["tasks"]) == sorted(ids[:2])
    assert counts["total"] == 25 and counts["counts"]["failed"] == 2
