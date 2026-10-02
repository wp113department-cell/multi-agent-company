"""Qoder cross-check ORCH-04-107 (2026-10-02): the task's pipeline/approve and
the approvals inbox could both resume the same plan graph (or a double click
could). The resume now claims pipeline_state atomically; a duplicate approval
finds nothing to claim. Real Postgres; the graph resume itself is a counter.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import new_isolated_async_engine


def test_two_simultaneous_approvals_resume_the_plan_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.agents as agents_api
    import app.pipeline.graph as graph

    calls = {"n": 0}

    async def counting_resume(**_k: Any) -> dict[str, Any]:
        calls["n"] += 1
        await asyncio.sleep(0.2)
        return {"stage": "rejected"}

    monkeypatch.setattr(graph, "resume_pipeline", counting_resume)

    async def scenario() -> tuple[int, str]:
        engine = new_isolated_async_engine()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(agents_api, "get_session_factory", lambda: factory)
        try:
            async with factory() as db:
                tid = (
                    await db.execute(
                        text(
                            "INSERT INTO dev_tasks (title, description, status) "
                            "VALUES ('qoder 04107', 'x', 'planning') RETURNING id"
                        )
                    )
                ).scalar_one()
                await db.execute(
                    text(
                        "INSERT INTO pipeline_state (task_id, stage) "
                        "VALUES (:t, 'awaiting_approval')"
                    ),
                    {"t": tid},
                )
                await db.commit()
            await asyncio.gather(
                agents_api.resume_planning_pipeline(int(tid), approved=False),
                agents_api.resume_planning_pipeline(int(tid), approved=False),
            )
            async with factory() as db:
                stage = (
                    await db.execute(
                        text("SELECT stage FROM pipeline_state WHERE task_id = :t"),
                        {"t": tid},
                    )
                ).scalar_one()
                for tbl, col in (
                    ("task_logs", "task_id"),
                    ("pipeline_state", "task_id"),
                ):
                    await db.execute(
                        text(f"DELETE FROM {tbl} WHERE {col} = :t"), {"t": tid}
                    )
                await db.execute(
                    text("DELETE FROM dev_tasks WHERE id = :t"), {"t": tid}
                )
                await db.commit()
            return calls["n"], str(stage)
        finally:
            await engine.dispose()

    n, stage = asyncio.run(scenario())
    assert n == 1, f"plan graph resumed {n} times for one plan"
    assert stage != "awaiting_approval"
