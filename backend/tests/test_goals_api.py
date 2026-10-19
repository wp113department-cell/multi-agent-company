"""Tests for Goals API (POST /api/goals, GET /api/goals, GET /api/goals/{id}).

G11 (2026-10-19): responses are camelCase (what apps/web/lib/api.ts always
expected), goal ids are UUIDs (a bad id is a 422), and the executive gets the
goal's project. The end-to-end flow with real Postgres is in
test_g11_goal_to_epics_e2e.py."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.goals import router
from app.db.session import get_db

G = [f"00000000-0000-0000-0000-00000000000{i}" for i in range(4)]


def _make_goal(goal_id: str = G[1], text: str = "Do stuff") -> SimpleNamespace:
    return SimpleNamespace(
        goal_id=goal_id,
        text=text,
        status="proposed",
        epic_ids=[],
        summary="We will do stuff.",
        project_id=None,
    )


def _make_test_app(db_override: AsyncMock) -> FastAPI:
    """Create a fresh FastAPI app with the goals router and a db override."""
    _app = FastAPI()
    _app.include_router(router)

    async def _override() -> AsyncGenerator[AsyncMock, None]:
        yield db_override

    _app.dependency_overrides[get_db] = _override
    return _app


class TestCreateGoal:
    @patch("app.api.goals.run_executive")
    def test_creates_goal_successfully(self, mock_exec: MagicMock) -> None:
        goal = _make_goal()
        db = AsyncMock()
        db.commit = AsyncMock()
        db.get = AsyncMock(return_value=goal)

        async def _exec(
            text: str, db_: object, **_kw: object
        ) -> tuple[str, list[str], None]:
            return G[1], ["e-1", "e-2"], None

        mock_exec.side_effect = _exec

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.post("/api/goals", json={"text": "Do stuff"})

        assert resp.status_code == 201
        data = resp.json()
        assert data["goalId"] == G[1]
        assert data["status"] == "proposed"

    def test_empty_text_returns_400(self) -> None:
        db = AsyncMock()
        app = _make_test_app(db)

        with TestClient(app) as client:
            resp = client.post("/api/goals", json={"text": "   "})

        assert resp.status_code == 400

    @patch("app.api.goals.run_executive")
    def test_executive_error_returns_500(self, mock_exec: MagicMock) -> None:
        db = AsyncMock()

        async def _exec(
            text: str, db_: object, **_kw: object
        ) -> tuple[str, list[str], str]:
            return "", [], "LLM exploded"

        mock_exec.side_effect = _exec

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.post("/api/goals", json={"text": "Do stuff"})

        assert resp.status_code == 500
        assert "LLM exploded" in resp.json()["detail"]

    @patch("app.api.goals.run_executive")
    def test_goal_not_found_after_creation_returns_500(
        self, mock_exec: MagicMock
    ) -> None:
        """If db.get returns None after flush, route returns 500."""
        db = AsyncMock()
        db.commit = AsyncMock()
        db.get = AsyncMock(return_value=None)

        async def _exec(
            text: str, db_: object, **_kw: object
        ) -> tuple[str, list[str], None]:
            return "g-1", ["e-1"], None

        mock_exec.side_effect = _exec

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.post("/api/goals", json={"text": "something"})

        assert resp.status_code == 500


class TestListGoals:
    def test_returns_list(self) -> None:
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value = [
            _make_goal(G[1]),
            _make_goal(G[2]),
        ]
        db.execute = AsyncMock(return_value=result)

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/goals")

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_empty_list(self) -> None:
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value = []
        db.execute = AsyncMock(return_value=result)

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/goals")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_goals_ordered_newest_first(self) -> None:
        db = AsyncMock()
        goals = [_make_goal(G[i]) for i in range(3)]
        result = MagicMock()
        result.scalars.return_value = goals
        db.execute = AsyncMock(return_value=result)

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/goals")

        assert resp.status_code == 200
        ids = [g["goalId"] for g in resp.json()]
        assert ids == G[:3]


class TestGetGoal:
    def test_returns_goal(self) -> None:
        db = AsyncMock()
        db.get = AsyncMock(return_value=_make_goal(G[2]))

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.get(f"/api/goals/{G[2]}")

        assert resp.status_code == 200
        assert resp.json()["goalId"] == G[2]

    def test_not_found_returns_404(self) -> None:
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.get(f"/api/goals/{G[3]}")

        assert resp.status_code == 404

    def test_summary_in_response(self) -> None:
        db = AsyncMock()
        goal = _make_goal(G[3])
        db.get = AsyncMock(return_value=goal)

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.get(f"/api/goals/{G[3]}")

        assert resp.json()["summary"] == "We will do stuff."
