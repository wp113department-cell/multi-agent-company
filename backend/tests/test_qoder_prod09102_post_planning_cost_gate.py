"""Qoder cross-check PROD-09-102 (2026-10-02): the epic cost gate estimated
5 subtasks before planning and never re-checked the real count, so an epic
estimated cheap could plan 30+ subtasks and run well over the threshold with
no approval. The planning node now re-checks (honouring an approved amount).
Real Postgres; planning and the estimator are patched (no LLM).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import new_isolated_async_engine


def _run_planning(
    monkeypatch: pytest.MonkeyPatch, approved: str | None
) -> tuple[str, str, str | None]:
    import app.pipeline.cost_controller as cc
    import app.pipeline.graph as pg
    from app.agents.manager import _planning_node

    real = cc.estimate_epic_cost

    async def scaled(subtask_count: int, db: Any) -> Any:
        base = await real(subtask_count=subtask_count, db=db)
        cost = 0.1 * subtask_count  # 5 -> $0.50 (under $1), 30 -> $3.00 (over)
        return replace(base, estimated_cost_usd=cost, requires_approval=cost > 1.0)

    async def thirty_subtasks(**_k: Any) -> dict[str, Any]:
        return {
            "subtasks": [
                {"id": i, "type": "backend", "title": f"s{i}"} for i in range(30)
            ],
            "task_description": "plan",
        }

    monkeypatch.setattr(cc, "estimate_epic_cost", scaled)
    monkeypatch.setattr(pg, "run_planning_pipeline", thirty_subtasks)

    async def run() -> tuple[str, str, str | None]:
        engine = new_isolated_async_engine()
        eid = str(uuid.uuid4())
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                await db.execute(
                    text(
                        "INSERT INTO epics (epic_id, title, description, status, "
                        "cost_approved_usd) VALUES (:e, 'qoder 09102', 'goal', 'pending', :a)"
                    ),
                    {"e": eid, "a": approved},
                )
                await db.commit()
                out = await _planning_node(
                    {"epic_id": eid, "goal": "goal", "db": db, "repo": "/tmp"}  # type: ignore[typeddict-item]
                )
                epic_status = (
                    await db.execute(
                        text("SELECT status FROM epics WHERE epic_id = :e"), {"e": eid}
                    )
                ).scalar_one()
                task_status = (
                    await db.execute(
                        text("SELECT status FROM dev_tasks WHERE epic_id = :e"),
                        {"e": eid},
                    )
                ).scalar_one_or_none()
                await db.execute(
                    text(
                        "DELETE FROM task_logs WHERE task_id IN "
                        "(SELECT id FROM dev_tasks WHERE epic_id = :e)"
                    ),
                    {"e": eid},
                )
                await db.execute(
                    text("DELETE FROM dev_tasks WHERE epic_id = :e"), {"e": eid}
                )
                await db.execute(
                    text("DELETE FROM epics WHERE epic_id = :e"), {"e": eid}
                )
                await db.commit()
                return str(out.get("stage", "")), str(epic_status), task_status
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_bigger_real_plan_is_sent_back_for_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage, epic_status, task_status = _run_planning(monkeypatch, approved=None)
    assert stage == "pending_cost_approval"
    assert epic_status == "pending_cost_approval"
    assert task_status == "cancelled", "the set-aside plan's task was left hanging"


def test_plan_within_the_approved_amount_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage, epic_status, _ = _run_planning(monkeypatch, approved="3.5")
    assert stage != "pending_cost_approval"
    assert epic_status != "pending_cost_approval"
