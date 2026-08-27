"""Tests for GET /api/fleet/reports/barot-agent-pool (app/api/fleet_dashboard.py)
— live, in-process TemporaryAgentPool state, no DB involved (unlike this
router's other /reports/* endpoints)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.temporary_agent import get_temporary_agent_pool
from app.api.fleet_dashboard import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_report_shape_with_no_live_slots() -> None:
    with _client() as client:
        resp = client.get("/api/fleet/reports/barot-agent-pool")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert isinstance(data["maxConcurrent"], int)
    assert isinstance(data["slotsUsed"], int)
    assert isinstance(data["slotsFree"], int)
    assert isinstance(data["slots"], list)


def test_report_reflects_a_live_slot() -> None:
    pool = get_temporary_agent_pool()
    slot = pool.spawn(
        task_id="1",
        required_capability="td_pool_report_cap",
        task_description="task",
        briefing="briefing",
        tool_names=["read_file"],
        model="test-model",
        repo_path="/tmp",
    )
    assert slot is not None
    try:
        with _client() as client:
            resp = client.get("/api/fleet/reports/barot-agent-pool")
        data = resp.json()
        names = [s["role_name"] for s in data["slots"]]
        assert slot.role_name in names
        assert data["slotsUsed"] >= 1
    finally:
        pool.scrap(slot.role_name, reason="test_cleanup")


def test_slots_free_never_negative_when_over_capacity() -> None:
    """Defensive: max() floor even if somehow over-capacity (e.g. a
    concurrent config decrease mid-run)."""
    pool = get_temporary_agent_pool()
    slots = []
    try:
        for i in range(3):
            s = pool.spawn(
                task_id=str(i),
                required_capability=f"td_pool_report_cap_{i}",
                task_description="task",
                briefing="briefing",
                tool_names=["read_file"],
                model="test-model",
                repo_path="/tmp",
            )
            assert s is not None
            slots.append(s)

        with _client() as client:
            resp = client.get("/api/fleet/reports/barot-agent-pool")
        data = resp.json()
        assert data["slotsFree"] >= 0
    finally:
        for s in slots:
            pool.scrap(s.role_name, reason="test_cleanup")
