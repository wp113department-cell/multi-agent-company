"""Tests for the Fleet Dashboard API (Day 9): list/detail/approve/reject.

Mocks app.db.session.get_db (same convention as test_goals_api.py) so these
tests never touch the real database and can't hit the asyncio-event-loop
pitfalls that app.agents.tools' DB-backed tools have their own dedicated
tests for in test_day9_fleet_agents.py.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.fleet_dashboard import router
from app.db.session import get_db


def _make_row(**overrides: Any) -> SimpleNamespace:
    base = dict(
        id=1,
        agent_name="agent_debugger",
        title="Test issue",
        description="Test description",
        category="bug",
        priority="medium",
        evidence={"k": "v"},
        status="pending",
        files_touched=[],
        commit_sha=None,
        restart_required=False,
        error=None,
        trace_id=None,
        created_at=datetime.now(timezone.utc),
        decided_at=None,
        decided_by=None,
        completed_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_test_app(db: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def _override() -> AsyncGenerator[AsyncMock, None]:
        yield db

    app.dependency_overrides[get_db] = _override
    return app


class TestListRequests:
    def test_returns_serialized_list(self) -> None:
        db = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [_make_row(), _make_row(id=2, priority="low")]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=mock_result)

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/fleet/requests")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["agentName"] == "agent_debugger"
        assert data[0]["status"] == "pending"

    def test_empty_list(self) -> None:
        db = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=mock_result)

        app = _make_test_app(db)
        with TestClient(app) as client:
            resp = client.get("/api/fleet/requests")

        assert resp.status_code == 200
        assert resp.json() == []


class TestGetRequest:
    def test_found(self) -> None:
        db = AsyncMock()
        db.get = AsyncMock(return_value=_make_row())
        app = _make_test_app(db)

        with TestClient(app) as client:
            resp = client.get("/api/fleet/requests/1")

        assert resp.status_code == 200
        assert resp.json()["id"] == 1

    def test_not_found(self) -> None:
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        app = _make_test_app(db)

        with TestClient(app) as client:
            resp = client.get("/api/fleet/requests/999")

        assert resp.status_code == 404


class TestApprove:
    @patch("app.api.fleet_dashboard.asyncio.create_task")
    def test_approve_pending_request(self, mock_create_task: MagicMock) -> None:
        db = AsyncMock()
        row = _make_row(status="pending")
        db.get = AsyncMock(return_value=row)
        db.commit = AsyncMock()
        app = _make_test_app(db)

        with TestClient(app) as client:
            resp = client.post("/api/fleet/requests/1/approve", json={"decided_by": "tester"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "in_progress"
        assert body["traceId"]
        assert row.status == "in_progress"
        assert row.decided_by == "tester"
        # the APPLY phase must be scheduled as a background task, not run inline
        # (never block the HTTP response on a full agent run)
        mock_create_task.assert_called_once()

    def test_approve_missing_request_404(self) -> None:
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        app = _make_test_app(db)

        with TestClient(app) as client:
            resp = client.post("/api/fleet/requests/999/approve")

        assert resp.status_code == 404

    def test_approve_already_decided_409(self) -> None:
        db = AsyncMock()
        db.get = AsyncMock(return_value=_make_row(status="completed"))
        app = _make_test_app(db)

        with TestClient(app) as client:
            resp = client.post("/api/fleet/requests/1/approve")

        assert resp.status_code == 409


class TestReject:
    def test_reject_pending_request(self) -> None:
        db = AsyncMock()
        row = _make_row(status="pending")
        db.get = AsyncMock(return_value=row)
        db.commit = AsyncMock()
        app = _make_test_app(db)

        with TestClient(app) as client:
            resp = client.post("/api/fleet/requests/1/reject", json={"decided_by": "tester"})

        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        assert row.status == "rejected"
        assert row.decided_by == "tester"

    def test_reject_missing_request_404(self) -> None:
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        app = _make_test_app(db)

        with TestClient(app) as client:
            resp = client.post("/api/fleet/requests/999/reject")

        assert resp.status_code == 404

    def test_reject_already_decided_409(self) -> None:
        db = AsyncMock()
        db.get = AsyncMock(return_value=_make_row(status="rejected"))
        app = _make_test_app(db)

        with TestClient(app) as client:
            resp = client.post("/api/fleet/requests/1/reject")

        assert resp.status_code == 409


class TestApplyDispatch:
    def test_dispatch_covers_the_4_apply_capable_agents(self) -> None:
        from app.api.fleet_dashboard import _apply_dispatch

        dispatch = _apply_dispatch()
        assert set(dispatch.keys()) == {
            "agent_performance_reviewer", "agent_debugger", "knowledge_curator", "quality_auditor",
        }

    def test_advisor_excluded_scan_only_by_design(self) -> None:
        from app.api.fleet_dashboard import _apply_dispatch

        assert "agent_advisor" not in _apply_dispatch()


@pytest.mark.asyncio
async def test_run_apply_phase_marks_completed_on_verified_result() -> None:
    from app.agents.agent_result import AgentResult
    from app.api.fleet_dashboard import _run_apply_phase

    fake_result = AgentResult(summary="done", verified=True, status="completed")
    fake_row = _make_row(status="in_progress")

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session_cm)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    session_cm.get = AsyncMock(return_value=fake_row)
    session_cm.commit = AsyncMock()

    with patch("app.db.session.get_async_session", return_value=session_cm), \
         patch("app.api.fleet_dashboard._apply_dispatch", return_value={"agent_debugger": MagicMock(return_value=fake_result)}):
        await _run_apply_phase(1, "agent_debugger", "desc", "trace-1")

    assert fake_row.status == "completed"
    assert fake_row.restart_required is True


@pytest.mark.asyncio
async def test_run_apply_phase_marks_failed_on_exception() -> None:
    from app.api.fleet_dashboard import _run_apply_phase

    fake_row = _make_row(status="in_progress")

    session_cm = AsyncMock()
    session_cm.__aenter__ = AsyncMock(return_value=session_cm)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    session_cm.get = AsyncMock(return_value=fake_row)
    session_cm.commit = AsyncMock()

    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")

    with patch("app.db.session.get_async_session", return_value=session_cm), \
         patch("app.api.fleet_dashboard._apply_dispatch", return_value={"agent_debugger": _raise}):
        await _run_apply_phase(1, "agent_debugger", "desc", "trace-1")

    assert fake_row.status == "failed"
    assert fake_row.error is not None
    assert "boom" in fake_row.error
