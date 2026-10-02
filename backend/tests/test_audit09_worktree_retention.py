"""Production audit 09 (2026-10-02): finished tasks' worktrees are reclaimed.

Before: only reject/complete/push-approval removed a worktree, so each failed or
cancelled task kept a full checkout on disk forever. Real Postgres; the
worktrees dir and the base repo are tmp dirs (never the real repo).
"""

from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db.models import DevTask
from app.db.session import new_isolated_async_engine
from app.services import retention


async def _make_tasks(specs: list[tuple[str, int]]) -> list[int]:
    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            tasks = [
                DevTask(title=f"audit09 wt {s}", description="x", status=s)
                for s, _ in specs
            ]
            db.add_all(tasks)
            await db.commit()
            for t, (_, age_days) in zip(tasks, specs):
                await db.execute(
                    text("UPDATE dev_tasks SET updated_at = :ts WHERE id = :id"),
                    {
                        "ts": datetime.now(timezone.utc) - timedelta(days=age_days),
                        "id": t.id,
                    },
                )
            await db.commit()
            return [t.id for t in tasks]
    finally:
        await engine.dispose()


async def _drop_tasks(ids: list[int]) -> None:
    engine = new_isolated_async_engine()
    try:
        async with async_sessionmaker(engine)() as db:
            await db.execute(
                text("DELETE FROM dev_tasks WHERE id = ANY(:ids)"), {"ids": ids}
            )
            await db.commit()
    finally:
        await engine.dispose()


def test_only_long_finished_task_worktrees_are_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_repo = tmp_path / "repo"
    base_repo.mkdir()
    subprocess.run(["git", "init", "-q", str(base_repo)], check=True)
    wt_dir = tmp_path / "worktrees"
    monkeypatch.setattr(get_settings(), "worktrees_dir", str(wt_dir))
    monkeypatch.setattr(get_settings(), "target_repo_path", str(base_repo))

    ids = asyncio.run(
        _make_tasks([("failed", 30), ("cancelled", 30), ("blocked", 30), ("failed", 1)])
    )
    old_failed, old_cancelled, old_blocked, new_failed = ids
    try:
        for tid in ids:
            (wt_dir / f"task-{tid}").mkdir(parents=True)
        (wt_dir / f"epic-e1/task-{old_cancelled}").mkdir(parents=True)
        (wt_dir / f"task-{old_cancelled}").rmdir()  # cancelled one lives in an epic dir

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        removed = asyncio.run(retention._cleanup_worktrees(cutoff))

        assert removed == 2
        assert not (wt_dir / f"task-{old_failed}").exists()
        assert not (wt_dir / f"epic-e1/task-{old_cancelled}").exists()
        assert (
            wt_dir / f"task-{old_blocked}"
        ).exists(), "blocked task lost its worktree"
        assert (
            wt_dir / f"task-{new_failed}"
        ).exists(), "recently failed task cleaned too early"
    finally:
        asyncio.run(_drop_tasks(ids))
