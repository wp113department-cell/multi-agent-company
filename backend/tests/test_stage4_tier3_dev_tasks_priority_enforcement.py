"""Stage 4 Tier 3 (2026-08-05, answer2.md Q2) — `DevTask.priority` is now
enforced at both real layers, not just documented as an intended value set.

Before this: `priority: str` was unconstrained everywhere — the Pydantic
request schema accepted any string, and the DB column had no CHECK
constraint, so any write path (the HTTP API, or any internal/programmatic
`create_task()` call) could store an arbitrary value. Confirmed live before
fixing: every existing `dev_tasks` row already had `priority='medium'`
(38/38), so migration 027's CHECK constraint needed no data cleanup.

Real migration was actually run against this environment's live Postgres
(`alembic upgrade head`, then `alembic downgrade 026` / `upgrade head`
again to prove the downgrade path is real too) before this test file was
written — not just authored and assumed to work.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.tasks import CreateTaskRequest
from app.db.repository import create_task
from app.db.session import new_isolated_async_engine


def test_pydantic_layer_rejects_an_invalid_priority_value() -> None:
    with pytest.raises(ValidationError):
        # Deliberately-invalid literal -- mypy correctly flags this
        # statically too (the type itself is real, not just documentation),
        # this test proves the matching runtime rejection.
        CreateTaskRequest(title="t", description="d", priority="banana")  # type: ignore[arg-type]


def test_pydantic_layer_accepts_all_three_real_values() -> None:
    for value in ("low", "medium", "high"):
        req = CreateTaskRequest(title="t", description="d", priority=value)
        assert req.priority == value


def test_pydantic_layer_default_is_medium() -> None:
    req = CreateTaskRequest(title="t", description="d")
    assert req.priority == "medium"


def test_db_layer_rejects_an_invalid_priority_value_via_direct_sql() -> None:
    """Proves the CHECK constraint itself, not just the Pydantic schema --
    covers any write path that bypasses the HTTP API entirely."""

    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with engine.connect() as conn:
                with pytest.raises(
                    Exception, match="ck_dev_tasks_priority_valid_values"
                ):
                    await conn.execute(
                        text(
                            "INSERT INTO dev_tasks (title, description, status, priority) "
                            "VALUES ('stage4 tier3 q2 test', 'x', 'pending', 'banana')"
                        )
                    )
                    await conn.commit()
                await conn.rollback()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_db_layer_accepts_real_create_task_calls_for_all_three_values() -> None:
    """End-to-end through the real create_task() repository function, not
    just a raw SQL probe -- proves the fix doesn't break the real write
    path for any of the 3 legitimate values."""

    async def _run() -> None:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                for value in ("low", "medium", "high"):
                    task = await create_task(
                        session,
                        f"stage4 tier3 q2 real create_task {value}",
                        "desc",
                        priority=value,
                    )
                    assert task.priority == value
        finally:
            await engine.dispose()

    asyncio.run(_run())
