"""Tests for Goals API (POST /api/goals, GET /api/goals, GET /api/goals/{id})."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.goals import router
from app.db.session import get_db


def _make_goal(goal_id: str = "g-1", text: str = "Do stuff") -> SimpleNamespace:
    return SimpleNamespace(
        goal_id=goal_id,
        text=text,
        status="processing",
        epic_ids=["e-1", "e-2"],
        summary="We will do stuff.",
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

        async def _exec(text: str, db_: object) -> tuple[str, list[str], None]:
            return "g-1", ["e-1", "e-2"], None

        mock_exec.side_effect = _exec

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.post("/api/goals", json={"text": "Do stuff"})

        assert resp.status_code == 201
        data = resp.json()
        assert data["goal_id"] == "g-1"
        assert data["epic_ids"] == ["e-1", "e-2"]

    def test_empty_text_returns_400(self) -> None:
        db = AsyncMock()
        app = _make_test_app(db)

        with TestClient(app) as client:
            resp = client.post("/api/goals", json={"text": "   "})

        assert resp.status_code == 400

    @patch("app.api.goals.run_executive")
    def test_executive_error_returns_500(self, mock_exec: MagicMock) -> None:
        db = AsyncMock()

        async def _exec(text: str, db_: object) -> tuple[str, list[str], str]:
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

        async def _exec(text: str, db_: object) -> tuple[str, list[str], None]:
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
        result.scalars.return_value.all.return_value = [
            _make_goal("g-1"),
            _make_goal("g-2"),
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
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/goals")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_goals_ordered_newest_first(self) -> None:
        db = AsyncMock()
        goals = [_make_goal(f"g-{i}") for i in range(3)]
        result = MagicMock()
        result.scalars.return_value.all.return_value = goals
        db.execute = AsyncMock(return_value=result)

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/goals")

        assert resp.status_code == 200
        ids = [g["goal_id"] for g in resp.json()]
        assert ids == ["g-0", "g-1", "g-2"]


class TestGetGoal:
    def test_returns_goal(self) -> None:
        db = AsyncMock()
        db.get = AsyncMock(return_value=_make_goal("g-abc"))

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/goals/g-abc")

        assert resp.status_code == 200
        assert resp.json()["goal_id"] == "g-abc"

    def test_not_found_returns_404(self) -> None:
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/goals/does-not-exist")

        assert resp.status_code == 404

    def test_summary_in_response(self) -> None:
        db = AsyncMock()
        goal = _make_goal("g-xyz")
        db.get = AsyncMock(return_value=goal)

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/goals/g-xyz")

        assert resp.json()["summary"] == "We will do stuff."
