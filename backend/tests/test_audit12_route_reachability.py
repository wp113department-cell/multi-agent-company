"""Production audit 12 (2026-10-02): routes the real UI calls must be reachable.

Found by the real-stack Playwright journey (no mocks):
- GET /api/epics/batch-review (the Daily Review page) returned 500 —
  GET /api/epics/{epic_id} was declared first and took "batch-review" as an
  epic UUID. The mocked e2e suite fulfilled the URL itself, so it never saw it.
- GET /api/fleet/requests/stream (NavBar's live stream, every page) was
  shadowed by /api/fleet/requests/{request_id} the same way.
Real Postgres; the epic/task rows are created and removed here.
"""

from __future__ import annotations

import asyncio
import importlib
import pkgutil
import uuid

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.api as api_pkg
from app.db.models import DevTask, Epic
from app.db.session import new_isolated_async_engine
from app.main import app


def test_no_route_is_shadowed_by_an_earlier_path_parameter() -> None:
    shadowed = []
    for m in pkgutil.iter_modules(api_pkg.__path__):
        router = getattr(importlib.import_module(f"app.api.{m.name}"), "router", None)
        if router is None:
            continue
        routes = [r for r in router.routes if isinstance(r, APIRoute)]
        for i, later in enumerate(routes):
            for earlier in routes[:i]:
                if (
                    earlier.methods & later.methods
                    and earlier.path != later.path
                    and earlier.path_regex.match(later.path)
                    and "{" not in later.path.split("/")[-1]
                ):
                    shadowed.append(f"{later.path} <- {earlier.path}")
    assert not shadowed, shadowed


async def _seed() -> tuple[str, int]:
    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            epic = Epic(
                epic_id=str(uuid.uuid4()),
                title="audit12 review epic",
                description="x",
                status="ready_for_review",
            )
            task = DevTask(
                title="audit12 review task", description="x", status="ready_for_review"
            )
            db.add_all([epic, task])
            await db.commit()
            return epic.epic_id, task.id
    finally:
        await engine.dispose()


async def _cleanup(epic_id: str, task_id: int) -> None:
    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine)() as db:
            await db.execute(
                text("DELETE FROM dev_tasks WHERE id = :i"), {"i": task_id}
            )
            await db.execute(
                text("DELETE FROM epics WHERE epic_id = :e"), {"e": epic_id}
            )
            await db.commit()
    finally:
        await engine.dispose()


def test_batch_review_returns_waiting_epics_and_tasks() -> None:
    epic_id, task_id = asyncio.run(_seed())
    try:
        with TestClient(app) as client:
            r = client.get("/api/epics/batch-review")
        assert r.status_code == 200, r.text
        body = r.json()
        epic = next(e for e in body["epics"] if e["epicId"] == epic_id)
        assert epic["age"] >= 0
        assert any(
            t.get("id") == task_id or t.get("taskId") == task_id for t in body["tasks"]
        )
    finally:
        asyncio.run(_cleanup(epic_id, task_id))


def test_logout_returns_204_and_clears_the_session_cookie() -> None:
    """Every real logout was a 500 (status_code=None response) and the
    httpOnly cookie was never cleared."""
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post("/api/auth/logout")
    assert r.status_code == 204
    cookie = r.headers.get("set-cookie", "")
    assert "gridiron_token=" in cookie
    assert "Max-Age=0" in cookie or "expires=" in cookie.lower()


def test_bad_input_is_a_4xx_not_a_500() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/api/epics/not-a-uuid").status_code == 422
        r = client.post("/api/tasks", json={"title": "   ", "description": "x"})
        assert r.status_code == 422
