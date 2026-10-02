"""Production audit 08 (PROD-08-006), owner's choice of in-app alerts:
GET /api/notifications lists recently blocked/failed tasks with their newest
error. Real Postgres; rows are created and removed here.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import new_isolated_async_engine
from app.main import app

_SPECS = [  # (title, status, blocked_reason, age_days, log)
    (
        "a08n blocked orphaned",
        "blocked",
        "orphaned",
        0,
        "Agent run lost while the task was coding",
    ),
    ("a08n failed recent", "failed", None, 1, None),
    ("a08n failed old", "failed", None, 30, None),
    ("a08n completed", "completed", None, 0, None),
]


async def _seed() -> list[int]:
    engine = new_isolated_async_engine()
    ids: list[int] = []
    try:
        async with async_sessionmaker(engine)() as db:
            for title, status, reason, age, log in _SPECS:
                tid = (
                    await db.execute(
                        text(
                            "INSERT INTO dev_tasks (title, description, status, blocked_reason, "
                            "updated_at) VALUES (:t, 'x', :s, :r, now() - make_interval(days => :a)) "
                            "RETURNING id"
                        ),
                        {"t": title, "s": status, "r": reason, "a": age},
                    )
                ).scalar_one()
                ids.append(int(tid))
                if log:
                    await db.execute(
                        text(
                            "INSERT INTO task_logs (task_id, category, message) "
                            "VALUES (:i, 'error', :m)"
                        ),
                        {"i": tid, "m": log},
                    )
            await db.commit()
        return ids
    finally:
        await engine.dispose()


async def _cleanup(ids: list[int]) -> None:
    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine)() as db:
            await db.execute(
                text("DELETE FROM task_logs WHERE task_id = ANY(:i)"), {"i": ids}
            )
            await db.execute(
                text("DELETE FROM dev_tasks WHERE id = ANY(:i)"), {"i": ids}
            )
            await db.commit()
    finally:
        await engine.dispose()


def test_recent_blocked_and_failed_tasks_are_notifications() -> None:
    ids = asyncio.run(_seed())
    blocked, failed_recent, failed_old, completed = ids
    try:
        with TestClient(app) as c:
            r = c.get("/api/notifications?limit=100")
        assert r.status_code == 200, r.text
        by_id = {i["taskId"]: i for i in r.json()["items"]}
        assert blocked in by_id and failed_recent in by_id
        assert failed_old not in by_id, "older than the 7-day window"
        assert completed not in by_id
        assert by_id[blocked]["message"].startswith("Agent run lost")
        assert by_id[blocked]["blockedReason"] == "orphaned"
        assert by_id[failed_recent]["message"] == "Task failed"
        ats = [i["at"] for i in r.json()["items"]]
        assert ats == sorted(ats, reverse=True), "newest first"
    finally:
        asyncio.run(_cleanup(ids))
