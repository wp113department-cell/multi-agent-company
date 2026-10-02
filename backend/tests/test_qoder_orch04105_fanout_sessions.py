"""Qoder cross-check ORCH-04-105 (2026-10-02): run_manager's fan-out passed
ONE AsyncSession to every concurrently dispatched subtask. SQLAlchemy sessions
are not safe for concurrent use and the write sites swallow errors, so status
rows/events could be lost silently. Concurrent subtasks now each get their own
session on the same engine; a single-subtask wave keeps the caller's session.
Real Postgres engine; the per-subtask work is a recorder (no agents run).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import new_isolated_async_engine


def test_concurrent_subtasks_get_their_own_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.agents.manager as manager

    seen: list[int] = []
    in_flight = {"now": 0, "peak": 0}

    async def recorder(**kw: Any) -> dict[str, Any]:
        session = kw["db"]
        seen.append(id(session))
        in_flight["now"] += 1
        in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
        await session.execute(text("SELECT pg_sleep(0.2)"))  # real concurrent use
        in_flight["now"] -= 1
        return {
            "result": {"subtask_id": kw["subtask"]["id"], "status": "completed"},
            "tokens_in": 0,
            "tokens_out": 0,
            "blocked": False,
        }

    monkeypatch.setattr(manager, "_dispatch_one_subtask", recorder)

    async def run() -> int:
        engine = new_isolated_async_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                await manager.run_manager(
                    task_id=999_777,
                    subtasks=[
                        {
                            "id": i,
                            "type": "backend",
                            "title": f"s{i}",
                            "description": "x",
                        }
                        for i in (1, 2, 3)
                    ],
                    worktree_path=str(tmp_path),
                    plan="plan",
                    repo_path=str(tmp_path),
                    db=db,
                    enable_fanout=True,
                )
                return id(db)
        finally:
            await engine.dispose()

    caller_session = asyncio.run(run())
    assert len(seen) == 3
    assert in_flight["peak"] == 3, "subtasks did not run concurrently"
    assert len(set(seen)) == 3, "concurrent subtasks shared a database session"
    assert caller_session not in seen
