"""Production audit 13 (2026-10-02, crash drill): after `kill -9` mid-run the
orphaned agent_run was reconciled to failed, but its task stayed "coding"
forever — shown as running in the UI with nothing running. Now the task is
blocked (blocked_reason="orphaned") with a log line; a task that still has a
live run is left alone. Real Postgres.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import new_isolated_async_engine
from app.fleet.failure_ladder import reconcile_orphaned_runs

_NEW_RUN = (
    "INSERT INTO agent_runs (id, task_id, agent_type, status, started_at, "
    "last_heartbeat_at) VALUES (gen_random_uuid(), :t, 'audit13_unresumable', "
    "'running', now() - make_interval(mins => :age), now() - make_interval(mins => :age))"
)


async def _scenario() -> tuple[tuple[str, str | None], str, int]:
    engine = new_isolated_async_engine()
    ids: list[int] = []
    try:
        async with async_sessionmaker(engine)() as db:
            for title in ("audit13 crashed", "audit13 still live"):
                row = await db.execute(
                    text(
                        "INSERT INTO dev_tasks (title, description, status) "
                        "VALUES (:t, 'x', 'coding') RETURNING id"
                    ),
                    {"t": title},
                )
                ids.append(int(row.scalar_one()))
            crashed, live = ids
            await db.execute(text(_NEW_RUN), {"t": crashed, "age": 40})
            await db.execute(text(_NEW_RUN), {"t": live, "age": 40})
            await db.execute(text(_NEW_RUN), {"t": live, "age": 0})  # healthy run
            await db.commit()

        await reconcile_orphaned_runs(threshold_seconds=1200)

        async with async_sessionmaker(engine)() as db:
            a = (
                await db.execute(
                    text("SELECT status, blocked_reason FROM dev_tasks WHERE id = :t"),
                    {"t": crashed},
                )
            ).one()
            b = (
                await db.execute(
                    text("SELECT status FROM dev_tasks WHERE id = :t"), {"t": live}
                )
            ).scalar_one()
            logs = (
                await db.execute(
                    text("SELECT count(*) FROM task_logs WHERE task_id = :t"),
                    {"t": crashed},
                )
            ).scalar_one()
        return (a[0], a[1]), b, int(logs)
    finally:
        async with async_sessionmaker(engine)() as db:
            await db.execute(
                text("DELETE FROM agent_runs WHERE task_id = ANY(:i)"), {"i": ids}
            )
            await db.execute(
                text("DELETE FROM task_logs WHERE task_id = ANY(:i)"), {"i": ids}
            )
            await db.execute(
                text("DELETE FROM dev_tasks WHERE id = ANY(:i)"), {"i": ids}
            )
            await db.commit()
        await engine.dispose()


def test_orphaned_run_blocks_its_task_unless_another_run_is_live() -> None:
    crashed, live_status, logs = asyncio.run(_scenario())
    assert crashed == ("blocked", "orphaned")
    assert logs >= 1, "no task log explains why the task was blocked"
    assert live_status == "coding", "a task with a healthy run must not be blocked"
