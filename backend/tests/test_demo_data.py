"""Client-demo data (scripts/seed_demo_data.py + app/services/demo.py).

Acting on demo items must never start real AI work, while real items behave
exactly as before. The seeder must be re-runnable and fully removable."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import func, select

from app.db.models import DevTask, EnhancementRequest, PendingApproval, Project
from app.main import app
from app.services.demo import DEMO_CREATOR


def _fresh() -> None:
    import app.db.session as sess

    sess._engine = None
    sess._session_factory = None


def _run(coro_fn: Any) -> Any:
    try:
        return asyncio.run(coro_fn())
    finally:
        _fresh()


def _call(method: str, url: str, json: Any = None) -> httpx.Response:
    async def go() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as c:
            return await c.request(method, url, json=json)

    return _run(go)


def _q(fn: Any) -> Any:
    from app.db.session import get_async_session

    async def go() -> Any:
        async with get_async_session() as db:
            return await fn(db)

    return _run(go)


@pytest.fixture()
def demo(tmp_path: Path) -> Any:
    from scripts.seed_demo_data import remove_demo, seed

    _run(lambda: seed(tmp_path))
    yield tmp_path

    async def rm() -> None:
        from app.db.session import get_async_session

        async with get_async_session() as db:
            await remove_demo(db)

    _run(rm)


def _task(title: str) -> DevTask:
    return _q(lambda db: _one(db, title))


async def _one(db: Any, title: str) -> DevTask:
    row = (
        await db.execute(
            select(DevTask).where(
                DevTask.title == title, DevTask.created_by == DEMO_CREATOR
            )
        )
    ).scalar_one()
    return row


def test_seed_creates_every_kind_of_demo_content_and_is_rerunnable(demo: Path) -> None:
    from scripts.seed_demo_data import seed

    async def counts(db: Any) -> tuple[int, int, int, set[str]]:
        p = (
            await db.execute(
                select(func.count())
                .select_from(Project)
                .where(Project.created_by == DEMO_CREATOR)
            )
        ).scalar_one()
        t = (
            await db.execute(
                select(func.count())
                .select_from(DevTask)
                .where(DevTask.created_by == DEMO_CREATOR)
            )
        ).scalar_one()
        e = (
            await db.execute(
                select(func.count())
                .select_from(EnhancementRequest)
                .where(EnhancementRequest.trace_id == DEMO_CREATOR)
            )
        ).scalar_one()
        st = {
            s
            for (s,) in await db.execute(
                select(DevTask.status).where(DevTask.created_by == DEMO_CREATOR)
            )
        }
        return int(p), int(t), int(e), st

    first = _q(counts)
    assert first[0] == 3 and first[1] >= 12 and first[2] == 5
    assert {
        "pending",
        "planning",
        "ready_for_review",
        "coding",
        "testing",
        "blocked",
        "completed",
        "failed",
    } <= first[3]
    assert (demo / "customer-support-assistant" / ".git").exists()
    _run(lambda: seed(demo))  # again: replaced, not duplicated
    assert _q(counts)[:3] == first[:3]


def test_starting_a_demo_task_uses_no_ai(demo: Path) -> None:
    t = _task("Weekly report of the top 10 customer questions")
    with (
        patch(
            "app.api.agents.launch_router",
            new=AsyncMock(side_effect=AssertionError("AI started")),
        ),
        patch(
            "app.api.agents.launch_planning_pipeline",
            new=AsyncMock(side_effect=AssertionError("AI started")),
        ),
    ):
        r = _call("POST", f"/api/tasks/{t.id}/run", {})
    assert r.status_code == 200 and r.json()["mode"] == "demo"
    assert _task(t.title).status == "planning"


def test_approving_a_demo_plan_uses_no_ai_and_closes_its_decision(demo: Path) -> None:
    t = _task("Live chat widget for the help centre")
    with patch(
        "app.api.agents.launch_coder",
        new=AsyncMock(side_effect=AssertionError("AI started")),
    ):
        r = _call("POST", f"/api/tasks/{t.id}/approve")
    assert r.status_code == 200
    assert _task(t.title).status == "coding"

    async def pending(db: Any) -> int:
        return int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(PendingApproval)
                    .where(
                        PendingApproval.task_id == t.id,
                        PendingApproval.status == "pending",
                    )
                )
            ).scalar_one()
        )

    assert _q(pending) == 0


def test_deciding_a_demo_approval_uses_no_ai(demo: Path) -> None:
    t = _task("Search products by colour and size")

    async def thread(db: Any) -> str:
        return str(
            (
                await db.execute(
                    select(PendingApproval.thread_id).where(
                        PendingApproval.task_id == t.id
                    )
                )
            ).scalar_one()
        )

    tid = _q(thread)
    with (
        patch(
            "app.api.agents.resume_planner_after_clarification",
            new=AsyncMock(side_effect=AssertionError),
        ),
        patch(
            "app.api.agents.resume_planning_pipeline",
            new=AsyncMock(side_effect=AssertionError),
        ),
    ):
        r = _call(
            "POST", f"/api/approvals/{tid}/approve", {"answer": "Shop sizes (S, M, L)"}
        )
    assert r.status_code == 200
    assert _task(t.title).status == "coding"


def test_approving_a_demo_suggestion_starts_no_apply_agent(demo: Path) -> None:
    async def first(db: Any) -> int:
        return int(
            (
                await db.execute(
                    select(EnhancementRequest.id)
                    .where(
                        EnhancementRequest.trace_id == DEMO_CREATOR,
                        EnhancementRequest.status == "pending",
                    )
                    .limit(1)
                )
            ).scalar_one()
        )

    rid = _q(first)
    with patch(
        "app.api.fleet_dashboard._run_apply_phase",
        new=AsyncMock(side_effect=AssertionError),
    ):
        r = _call("POST", f"/api/fleet/requests/{rid}/approve", {})
    assert r.status_code == 200 and r.json()["status"] == "applied"


def test_real_tasks_are_not_affected(demo: Path) -> None:
    created = _call(
        "POST", "/api/tasks", {"title": "real one", "description": "d"}
    ).json()
    with patch("app.api.agents.launch_router", new=AsyncMock()) as launched:
        r = _call("POST", f"/api/tasks/{created['id']}/run", {"mode": "auto"})
    assert r.status_code == 200 and r.json()["mode"] == "auto"
    assert launched.await_count + launched.call_count >= 1

    async def rm(db: Any) -> None:
        from sqlalchemy import delete

        await db.execute(delete(DevTask).where(DevTask.id == created["id"]))
        await db.commit()

    _q(rm)


def test_remove_leaves_no_demo_rows(tmp_path: Path) -> None:
    from scripts.seed_demo_data import remove_demo, seed

    _run(lambda: seed(tmp_path))

    async def go() -> int:
        from app.db.session import get_async_session

        async with get_async_session() as db:
            await remove_demo(db)
            return int(
                (
                    await db.execute(
                        select(func.count())
                        .select_from(DevTask)
                        .where(DevTask.created_by == DEMO_CREATOR)
                    )
                ).scalar_one()
            )

    assert _run(go) == 0
    assert (tmp_path / "shopnow-storefront" / "README.md").exists()  # files kept
