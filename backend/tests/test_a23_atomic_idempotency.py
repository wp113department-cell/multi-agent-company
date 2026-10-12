"""Sol A23 (2026-10-12): an Idempotency-Key is reserved atomically before
the work, so two identical requests arriving together do the work once.

Before: the key was checked before the work and stored after it, so two
simultaneous requests both passed the check and both created a task; a key
reused with a different body silently ran a new call; keys were shared
between users.
"""

from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.main import app

TITLE = "a23 idempotency task"


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
def as_user() -> Any:
    from app.middleware import rbac

    def use(user: str) -> None:
        app.dependency_overrides[rbac.require_approver] = lambda: user

    yield use
    app.dependency_overrides.clear()

    async def clean(s):  # type: ignore[no-untyped-def]
        from app.db.models import DevTask

        await s.execute(delete(DevTask).where(DevTask.title.like("a23 %")))
        await s.commit()

    _db(clean)


def _count() -> int:
    async def go(s):  # type: ignore[no-untyped-def]
        from app.db.models import DevTask

        rows = await s.execute(select(DevTask.id).where(DevTask.title == TITLE))
        return len(rows.all())

    return int(_db(go))


@pytest.fixture
def slow_create(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.tasks as tasks_api

    real = tasks_api.create_task

    async def slow(*a: Any, **k: Any) -> Any:
        await asyncio.sleep(0.6)  # both requests are in flight together
        return await real(*a, **k)

    monkeypatch.setattr(tasks_api, "create_task", slow)


def test_two_simultaneous_requests_create_one_task(
    as_user: Any, slow_create: None
) -> None:
    as_user("admin")
    key = f"a23-{uuid.uuid4()}"
    body = {"title": TITLE, "description": "d"}
    with TestClient(app) as client:
        with ThreadPoolExecutor(2) as pool:
            replies = list(
                pool.map(
                    lambda _: client.post(
                        "/api/tasks", json=body, headers={"Idempotency-Key": key}
                    ),
                    range(2),
                )
            )
        later = client.post("/api/tasks", json=body, headers={"Idempotency-Key": key})
    codes = sorted(r.status_code for r in replies)
    assert codes == [201, 409], [r.text for r in replies]
    assert _count() == 1
    first = next(r for r in replies if r.status_code == 201)
    assert later.status_code == 201 and later.json()["id"] == first.json()["id"]


def test_a_reused_key_with_a_different_request_conflicts(as_user: Any) -> None:
    as_user("admin")
    key = f"a23-{uuid.uuid4()}"
    with TestClient(app) as client:
        ok = client.post(
            "/api/tasks",
            json={"title": TITLE, "description": "d"},
            headers={"Idempotency-Key": key},
        )
        other = client.post(
            "/api/tasks",
            json={"title": "a23 something else", "description": "d"},
            headers={"Idempotency-Key": key},
        )
    assert ok.status_code == 201
    assert other.status_code == 409 and "different request" in other.text


def test_keys_belong_to_one_user(as_user: Any) -> None:
    key = f"a23-{uuid.uuid4()}"
    body = {"title": TITLE, "description": "d"}
    with TestClient(app) as client:
        as_user("admin")
        a = client.post("/api/tasks", json=body, headers={"Idempotency-Key": key})
        as_user("someone-else")
        b = client.post("/api/tasks", json=body, headers={"Idempotency-Key": key})
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] != b.json()["id"]  # not the other user's cached answer


def test_a_failed_request_frees_its_key(as_user: Any) -> None:
    as_user("admin")
    key = f"a23-{uuid.uuid4()}"
    body = {"title": TITLE, "description": "d", "project_id": 987654321}
    with TestClient(app) as client:
        first = client.post("/api/tasks", json=body, headers={"Idempotency-Key": key})
        again = client.post("/api/tasks", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 404
    assert again.status_code == 404  # a retry runs again, not "in progress"
