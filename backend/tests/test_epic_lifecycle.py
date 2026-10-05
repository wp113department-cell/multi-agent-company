"""Epic lifecycle (owner decision 2026-10-05; Qoder ORCH-04-103/104 + SEC-05-102).

plan -> (policy approval if protected paths) -> plan approval -> coding from the
SAVED plan -> ready_for_review -> approve = push/PR approval for the child task;
reject at any stage closes the epic and its child task.

Real Postgres; planning, coding, worktrees, host checks and the push-approval
writer are patched — no LLM, no git, no spend.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import new_isolated_async_engine

PLAN = {
    "subtasks": [
        {"id": 1, "type": "backend", "title": "add migration", "description": "x"},
        {"id": 2, "type": "backend", "title": "wire api", "description": "y"},
    ],
    "task_description": "the approved plan",
    "architect_plan": {
        "impacted_files": [
            {"path": "lifecycle_demo/one.py"},
            {"path": "lifecycle_demo/two.py"},
        ]
    },
}


@pytest.fixture()
def fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> dict[str, Any]:
    import app.agents.manager as manager
    import app.api.agents as agents_api
    import app.fleet.resource_check as rc
    import app.fleet.size_estimate as se
    import app.pipeline.cost_controller as cc
    import app.pipeline.graph as pg
    import app.repo_tools.worktree as wt
    from dataclasses import replace

    calls: dict[str, Any] = {"run_manager": 0, "push": []}

    monkeypatch.setattr(
        rc,
        "run_resource_check",
        lambda **_k: SimpleNamespace(
            sufficient=True,
            reasons=[],
            recommendations=[],
            disk_free_gb=500.0,
            ram_available_gb=64.0,
            cpu_count=8,
            docker_available=True,
            gpu_available=False,
        ),
    )

    async def small_size(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(
            estimated_disk_required_mb=1.0, estimated_memory_required_mb=1.0
        )

    monkeypatch.setattr(se, "estimate_project_size", small_size)
    real_cost = cc.estimate_epic_cost

    async def cheap(subtask_count: int, db: Any) -> Any:
        return replace(
            await real_cost(subtask_count=subtask_count, db=db),
            estimated_cost_usd=0.01,
            requires_approval=False,
        )

    monkeypatch.setattr(cc, "estimate_epic_cost", cheap)

    async def planned(**_k: Any) -> dict[str, Any]:
        return calls.get("plan_override", PLAN)

    monkeypatch.setattr(pg, "run_planning_pipeline", planned)
    monkeypatch.setattr(wt, "create_worktree", lambda *_a, **_k: tmp_path)

    async def fake_manager(**kw: Any) -> dict[str, Any]:
        calls["run_manager"] += 1
        calls["subtasks"] = kw["subtasks"]
        calls["plan"] = kw["plan"]
        return {
            "status": "completed",
            "results": [
                {"subtask_id": s["id"], "type": "backend", "status": "completed"}
                for s in kw["subtasks"]
            ],
            "blocked_count": 0,
            "tokens_in": 0,
            "tokens_out": 0,
        }

    monkeypatch.setattr(manager, "run_manager", fake_manager)

    async def record_push(db: Any, task_id: int, *a: Any, **k: Any) -> None:
        calls["push"].append(task_id)

    monkeypatch.setattr(agents_api, "_record_git_push_approval", record_push)
    return calls


async def _sql(q: str, **p: Any) -> Any:
    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine)() as db:
            r = await db.execute(text(q), p)
            await db.commit()
            return r.fetchall() if r.returns_rows else None
    finally:
        await engine.dispose()


async def _start_epic(policy_pattern: str | None = None) -> tuple[str, int | None]:
    from app.agents.manager import run_epic_manager

    eid = str(uuid.uuid4())
    await _sql(
        "INSERT INTO epics (epic_id, title, description, status) "
        "VALUES (:e, 'lifecycle test', 'goal', 'pending')",
        e=eid,
    )
    pid = None
    if policy_pattern:
        pid = (
            await _sql(
                "INSERT INTO policies (name, trigger_pattern, required_approval_role, "
                "blocking, active) VALUES ('lifecycle-migrations', :p, 'admin', true, "
                "true) RETURNING id",
                p=policy_pattern,
            )
        )[0][0]
    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await run_epic_manager(epic_id=eid, goal="goal", db=db)
    finally:
        await engine.dispose()
    return eid, pid


async def _status(eid: str) -> tuple[str, str | None, str | None]:
    epic = (await _sql("SELECT status FROM epics WHERE epic_id = :e", e=eid))[0][0]
    rows = await _sql(
        "SELECT t.status, p.stage FROM dev_tasks t LEFT JOIN pipeline_state p "
        "ON p.task_id = t.id WHERE t.epic_id = :e AND t.status <> 'cancelled' "
        "ORDER BY t.id DESC LIMIT 1",
        e=eid,
    )
    return str(epic), (rows[0][0] if rows else None), (rows[0][1] if rows else None)


async def _cleanup(eid: str, pid: int | None) -> None:
    await _sql(
        "DELETE FROM subtasks WHERE task_id IN (SELECT id FROM dev_tasks WHERE epic_id = :e)",
        e=eid,
    )
    for tbl in ("pipeline_state", "task_logs"):
        await _sql(
            f"DELETE FROM {tbl} WHERE task_id IN (SELECT id FROM dev_tasks WHERE epic_id = :e)",
            e=eid,
        )
    await _sql("DELETE FROM epic_file_locks WHERE epic_id = :e", e=eid)
    await _sql("DELETE FROM policy_approvals WHERE epic_id = :e", e=eid)
    await _sql("DELETE FROM dev_tasks WHERE epic_id = :e", e=eid)
    await _sql("DELETE FROM epics WHERE epic_id = :e", e=eid)
    if pid:
        await _sql("DELETE FROM policies WHERE id = :p", p=pid)


def test_plan_waits_for_approval_then_codes_from_the_saved_plan(
    fakes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.epics as epics_api
    from app.agents.manager import run_epic_after_plan_approval
    from app.main import app

    eid, pid = asyncio.run(_start_epic())
    try:
        assert asyncio.run(_status(eid)) == (
            "pending_plan_approval",
            "planning",
            "epic_plan_review",
        )
        assert fakes["run_manager"] == 0, "coding started before the plan was approved"

        async def no_launch(*_a: Any) -> None:
            return None

        monkeypatch.setattr(epics_api, "_launch_epic_after_plan", no_launch)
        with TestClient(app) as c:
            r = c.post(
                f"/api/epics/{eid}/approve-plan", headers={"X-User-Id": "approver-1"}
            )
            assert r.status_code == 200, r.text
        assert asyncio.run(_status(eid))[0] == "plan_approved"

        async def resume() -> None:
            engine = new_isolated_async_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                    await run_epic_after_plan_approval(eid, db)
            finally:
                await engine.dispose()

        asyncio.run(resume())
        assert fakes["run_manager"] == 1
        assert [s["title"] for s in fakes["subtasks"]] == ["add migration", "wire api"]
        assert fakes["plan"] == "the approved plan"
        epic_status, task_status, _ = asyncio.run(_status(eid))
        assert (epic_status, task_status) == ("ready_for_review", "ready_for_review")

        with TestClient(app) as c:
            r = c.post(f"/api/epics/{eid}/approve", headers={"X-User-Id": "approver-1"})
            assert r.status_code == 200, r.text
            assert r.json()["pushApprovalRequested"] is True
        assert len(fakes["push"]) == 1, "no push / PR approval was created"
        assert asyncio.run(_status(eid))[0] == "approved"
    finally:
        asyncio.run(_cleanup(eid, pid))


def test_protected_paths_need_policy_approval_first(fakes: dict[str, Any]) -> None:
    from app.main import app

    fakes["plan_override"] = {
        **PLAN,
        "architect_plan": {
            "impacted_files": [{"path": "lifecycle_protected/secret.py"}]
        },
    }
    eid, pid = asyncio.run(_start_epic(policy_pattern="lifecycle_protected/**"))
    try:
        assert asyncio.run(_status(eid))[0] == "pending_policy_approval"
        with TestClient(app) as c:
            r = c.post(
                f"/api/epics/{eid}/approve-plan", headers={"X-User-Id": "approver-1"}
            )
            assert (
                r.status_code == 409
            ), "plan approved while a protected path was unapproved"
            r = c.post(
                f"/api/epics/{eid}/policy-approval",
                json={"policy_id": pid, "decision": "approved"},
                headers={"X-User-Id": "approver-1"},
            )
            assert r.status_code == 200, r.text
        assert asyncio.run(_status(eid))[0] == "pending_plan_approval"
    finally:
        asyncio.run(_cleanup(eid, pid))


def test_rejecting_the_plan_closes_epic_and_child_task(fakes: dict[str, Any]) -> None:
    from app.main import app

    eid, pid = asyncio.run(_start_epic())
    try:
        with TestClient(app) as c:
            r = c.post(
                f"/api/epics/{eid}/reject-plan", headers={"X-User-Id": "approver-1"}
            )
            assert r.status_code == 200, r.text
        epic_status, task_status, _ = asyncio.run(_status(eid))
        assert (epic_status, task_status) == ("rejected", "rejected")
        assert fakes["run_manager"] == 0
    finally:
        asyncio.run(_cleanup(eid, pid))
