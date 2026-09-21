"""Verification batch B5 (#353/#354/#368-#372) — the pre-execution cost estimate against a real database.

Defect proven before the fix: `_historical_avg_tokens` averaged EVERY completed agent_run in the table,
so tiny guardian/test/utility runs dragged "tokens per subtask" to a few hundred (80 on the dev
database) and a real epic never reached the approval threshold. A subtask costs the developer's run
plus the qa and reviewer runs that check it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import AgentRun, DevTask
from app.pipeline.cost_controller import _historical_avg_tokens, estimate_epic_cost

pytestmark = pytest.mark.skipif(
    not get_settings().database_url, reason="requires a real DATABASE_URL"
)

RELEVANT = ("backend_dev", "frontend_dev", "coder", "qa", "reviewer")


async def _seed(db, rows: list[tuple[str, int, int]]) -> None:
    task = DevTask(title="b5 estimate probe", description="x", status="completed")
    db.add(task)
    await db.flush()
    for agent, tin, tout in rows:
        db.add(
            AgentRun(
                id=uuid.uuid4().hex,
                task_id=task.id,
                agent_type=agent,
                status="completed",
                tokens_in=tin,
                tokens_out=tout,
            )
        )
    await db.flush()


@pytest.fixture
async def db():
    """A transaction that is always rolled back — the estimate must be judged against a
    known table, and nothing here may touch rows other tests own."""
    engine = create_async_engine(get_settings().database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await session.execute(delete(AgentRun).where(AgentRun.agent_type.in_(RELEVANT)))
        yield session
        await session.rollback()
    await engine.dispose()


async def test_tiny_unrelated_runs_do_not_dilute_the_per_subtask_estimate(db) -> None:
    await _seed(
        db,
        [
            ("backend_dev", 60_000, 9_000),
            ("qa", 20_000, 3_000),
            ("reviewer", 10_000, 2_000),
        ]
        + [("guardian_x", 80, 20)] * 200,
    )
    assert await _historical_avg_tokens(db) == (90_000, 14_000)
    est = await estimate_epic_cost(subtask_count=5, db=db)
    assert est.estimated_tokens_in == 450_000
    assert est.estimated_cost_usd > 1.0 and est.requires_approval is True


async def test_no_developer_history_falls_back_to_config_coefficients(db) -> None:
    await _seed(db, [("qa", 20_000, 3_000), ("guardian_x", 80, 20)])
    assert await _historical_avg_tokens(db) == (None, None)
    est = await estimate_epic_cost(subtask_count=5, db=db)
    assert est.historical_avg_tokens_in is None
    assert est.estimated_tokens_in == 5 * get_settings().cost_tokens_per_subtask


async def test_the_estimate_reports_duration_and_a_cheaper_scope(db) -> None:
    est = await estimate_epic_cost(subtask_count=8, db=db)
    assert est.estimated_duration_seconds > 0 and est.duration_source in (
        "historical",
        "config_fallback",
    )
    assert est.cost_per_subtask_usd > 0
    assert est.max_subtasks_within_threshold == int(
        get_settings().cost_approval_threshold // est.cost_per_subtask_usd
    )
