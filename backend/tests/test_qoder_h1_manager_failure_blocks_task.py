"""Qoder cross-check H-1 (2026-10-02): when launch_manager's pipeline raised,
only pipeline_state became "blocked"; the task stayed "coding" forever (no run,
not restartable, invisible to the alert bell). Real Postgres; the manager,
worktree creation and alert are patched so nothing touches a real repo.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import new_isolated_async_engine


def test_manager_crash_leaves_task_blocked_not_coding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    import app.agents.manager as manager_mod
    import app.api.agents as agents_api

    async def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("simulated manager crash")

    async def no_alert(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(manager_mod, "run_manager", boom)
    monkeypatch.setattr(agents_api, "send_task_alert", no_alert)
    monkeypatch.setattr(agents_api, "create_worktree", lambda *_a, **_k: tmp_path)

    async def scenario() -> tuple[str, int]:
        engine = new_isolated_async_engine()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(agents_api, "get_session_factory", lambda: factory)
        try:
            async with factory() as db:
                tid = (
                    await db.execute(
                        text(
                            "INSERT INTO dev_tasks (title, description, status) "
                            "VALUES ('qoder h1', 'x', 'ready_for_review') RETURNING id"
                        )
                    )
                ).scalar_one()
                await db.commit()
            await agents_api.launch_manager(
                int(tid), [{"title": "s", "type": "backend"}], "plan", str(tmp_path)
            )
            async with factory() as db:
                status = (
                    await db.execute(
                        text("SELECT status FROM dev_tasks WHERE id = :i"), {"i": tid}
                    )
                ).scalar_one()
                logs = (
                    await db.execute(
                        text(
                            "SELECT count(*) FROM task_logs WHERE task_id = :i "
                            "AND category = 'pipeline_error'"
                        ),
                        {"i": tid},
                    )
                ).scalar_one()
                await db.execute(
                    text("DELETE FROM task_logs WHERE task_id = :i"), {"i": tid}
                )
                await db.execute(
                    text("DELETE FROM pipeline_state WHERE task_id = :i"), {"i": tid}
                )
                await db.execute(
                    text("DELETE FROM dev_tasks WHERE id = :i"), {"i": tid}
                )
                await db.commit()
            return str(status), int(logs)
        finally:
            await engine.dispose()

    status, logs = asyncio.run(scenario())
    assert status == "blocked", f"task left in {status!r} after the manager crashed"
    assert logs >= 1
