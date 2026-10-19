"""G11 (2026-10-19): goal → executive → epics → start, end to end.

Real API, real Postgres; only the model is faked (the executive's single
graph call) and the epic manager pipeline launch is captured, so no paid
call happens.

Before: POST /api/goals created epics that belonged to no project and no
code folder, so they never showed anywhere and could never run, and the
goal stayed "processing" for ever. Now the goal and its epics belong to the
project, the epics are "proposed" until the user starts one, and the goal's
status follows its epics.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

PLAN = {
    "summary": "Customers can pay online.",
    "epics": [
        {"title": "Payment page", "description": "Card form and checkout."},
        {"title": "Receipts", "description": "Email a receipt after payment."},
    ],
}


def _db(fn):  # type: ignore[no-untyped-def]
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.session import new_isolated_async_engine

    async def run():  # type: ignore[no-untyped-def]
        engine = new_isolated_async_engine()
        try:
            async with AsyncSession(engine, expire_on_commit=False) as s:
                result = await fn(s)
                await s.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(run())


@pytest.fixture
def projects(tmp_path: Path) -> Any:
    """One project with a code folder, one without."""
    from sqlalchemy import delete

    from app.db.models import Epic, Goal, Project, Repo

    async def make(s):  # type: ignore[no-untyped-def]
        repo = Repo(name="g11", github_url="", local_path=str(tmp_path), status="ready")
        s.add(repo)
        await s.flush()
        with_code = Project(name="G11 shop", repo_id=repo.id, source="local_existing")
        no_code = Project(name="G11 idea", source="local_new")
        s.add_all([with_code, no_code])
        await s.flush()
        return with_code.id, no_code.id, repo.id

    with_code, no_code, repo_id = _db(make)
    yield with_code, no_code, repo_id

    async def clean(s):  # type: ignore[no-untyped-def]
        ids = [with_code, no_code]
        await s.execute(delete(Epic).where(Epic.project_id.in_(ids)))
        await s.execute(delete(Goal).where(Goal.project_id.in_(ids)))
        await s.execute(delete(Project).where(Project.id.in_(ids)))
        await s.execute(delete(Repo).where(Repo.id == repo_id))

    _db(clean)


def _fake_model(**_kw: Any) -> dict[str, Any]:
    return {
        "messages": [{"role": "assistant", "content": json.dumps(PLAN)}],
        "tokens_in": 10,
        "tokens_out": 20,
    }


def _client() -> TestClient:
    from app.middleware import rbac

    for dep in ("require_authenticated", "require_approver"):
        app.dependency_overrides[getattr(rbac, dep)] = lambda: "owner"
    return TestClient(app)


def _break_down(client: TestClient, project_id: int) -> dict[str, Any]:
    with patch("app.agents.executive.run_agent_graph", side_effect=_fake_model):
        r = client.post(
            "/api/goals",
            json={"text": "Take payments online", "project_id": project_id},
        )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def test_a_goal_becomes_epics_of_its_project_and_they_start(projects: Any) -> None:
    with_code, _, repo_id = projects
    launched: list[str] = []

    async def fake_launch(epic_id: str, goal: str) -> None:
        launched.append(epic_id)

    try:
        with _client() as client:
            goal = _break_down(client, with_code)
            assert goal["status"] == "proposed" and goal["projectId"] == with_code
            assert [e["title"] for e in goal["epics"]] == ["Payment page", "Receipts"]
            assert {e["status"] for e in goal["epics"]} == {"proposed"}

            # the project page shows the goal and its epics
            page = client.get(f"/api/projects/{with_code}").json()
            assert [g["status"] for g in page["goals"]] == ["proposed"]
            assert {e["title"] for e in page["epics"]} == {"Payment page", "Receipts"}
            listed = client.get(f"/api/goals?project_id={with_code}").json()
            assert [g["goalId"] for g in listed] == [goal["goalId"]]

            first = goal["epics"][0]["epicId"]
            with patch("app.api.epics._launch_epic_manager", side_effect=fake_launch):
                started = client.post(f"/api/epics/{first}/start")
                again = client.post(f"/api/epics/{first}/start")
            assert started.status_code == 200 and started.json()["status"] == "pending"
            assert again.status_code == 409  # never started twice
            assert launched == [first]

            after = client.get(f"/api/goals/{goal['goalId']}").json()
            assert after["status"] == "in_progress"
    finally:
        app.dependency_overrides.clear()

    from app.db.models import Epic

    async def finish(s):  # type: ignore[no-untyped-def]
        epics = [await s.get(Epic, e["epicId"]) for e in goal["epics"]]
        assert all(e.repo_id == repo_id for e in epics)  # they run in its folder
        for e in epics:
            e.status = "approved"

    _db(finish)
    try:
        with _client() as client:
            assert client.get(f"/api/goals/{goal['goalId']}").json()["status"] == "done"
    finally:
        app.dependency_overrides.clear()


def test_an_epic_of_a_project_without_code_cannot_start(projects: Any) -> None:
    _, no_code, _ = projects
    try:
        with _client() as client:
            goal = _break_down(client, no_code)
            epic = goal["epics"][0]["epicId"]
            with patch("app.api.epics._launch_epic_manager") as launch:
                r = client.post(f"/api/epics/{epic}/start")
            assert (
                r.status_code == 400
                and "no code folder" in r.json()["error"]["message"]
            )
            launch.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_unknown_project_and_bad_goal_id(projects: Any) -> None:
    try:
        with _client() as client:
            r = client.post("/api/goals", json={"text": "x", "project_id": 999999999})
            assert r.status_code == 404
            assert client.get("/api/goals/not-a-uuid").status_code == 422
    finally:
        app.dependency_overrides.clear()
