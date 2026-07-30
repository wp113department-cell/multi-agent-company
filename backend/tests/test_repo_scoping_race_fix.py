"""Gap-closure Day 4 (answers.md root-cause 1c, Q51/Q94/Q95) — real-DB proof
that a task's own dispatch always uses the repo it was actually created
against (task.repo_id), never whichever repo happens to be globally active
at the arbitrarily-later moment a background task actually executes.

This is the exact acceptance criterion from the gap-closure plan: "two repos
activated back-to-back with in-flight dispatches, each dispatch proven to
use the repo active at its own request time." Real scenario reproduced here:
Task 1 is created against Repo A; before its approval decision is dispatched,
someone activates Repo B globally (a real, previously-possible race — see
app.db.repository.resolve_task_repo_path's docstring for the exact bug this
closes). The dispatch must still resolve Repo A, not Repo B, and not silently
fall through to None.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.models import DevTask, Repo
from app.db.repository import create_task, get_task, resolve_task_repo_path
from app.fleet.approval_gate import PendingApprovalRecord


def _engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def _make_repo(session: AsyncSession, suffix: str, ready: bool = True) -> Repo:
    repo = Repo(
        github_url=f"https://github.com/test/race-{suffix}",
        name=f"race-{suffix}",
        local_path=f"/tmp/race-{suffix}",
        status="ready" if ready else "cloning",
    )
    session.add(repo)
    await session.commit()
    await session.refresh(repo)
    return repo


@pytest.mark.asyncio
async def test_resolve_task_repo_path_uses_task_repo_id_not_the_global() -> None:
    """The core helper: proves it reads task.repo_id, and is structurally
    incapable of reading the mutable global — it never imports app.api.repo
    at all."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = await _make_repo(session, f"a-{suffix}")
            repo_b = await _make_repo(session, f"b-{suffix}")

            created = await create_task(
                session, f"task-{suffix}", "test task", repo_id=repo_a.id
            )
            task = await get_task(session, created.id)
            assert task is not None

            resolved = resolve_task_repo_path(task)
            assert resolved == repo_a.local_path
            assert resolved != repo_b.local_path

            await session.execute(delete(DevTask).where(DevTask.id == task.id))
            await session.execute(
                delete(Repo).where(Repo.id.in_([repo_a.id, repo_b.id]))
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_task_repo_path_returns_none_for_not_ready_repo() -> None:
    """A repo that's still cloning (not 'ready') must not be resolved as
    usable — matches the existing run_task/restart_task/approve_task
    convention this helper replaces."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo = await _make_repo(session, f"notready-{suffix}", ready=False)
            created = await create_task(
                session, f"task-{suffix}", "test task", repo_id=repo.id
            )
            task = await get_task(session, created.id)
            assert task is not None

            assert resolve_task_repo_path(task) is None

            await session.execute(delete(DevTask).where(DevTask.id == task.id))
            await session.execute(delete(Repo).where(Repo.id == repo.id))
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dispatch_decision_uses_tasks_own_repo_even_if_global_changed_meanwhile() -> (
    None
):
    """The real acceptance criterion, at the actual call site that had the
    bug: create Task 1 against Repo A, then simulate someone activating
    Repo B globally before the approval decision is dispatched (a real
    sequence — approval can be arbitrarily delayed). _dispatch_decision must
    still resolve Repo A's path, proven by intercepting the real
    resume_planning_pipeline call rather than running the full pipeline."""
    engine = _engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repo_a = await _make_repo(session, f"dispatch-a-{suffix}")
            repo_b = await _make_repo(session, f"dispatch-b-{suffix}")

            task = await create_task(
                session, f"task-{suffix}", "test task", repo_id=repo_a.id
            )

            row = PendingApprovalRecord(
                id=1,
                thread_id=f"task-{task.id}",
                task_id=task.id,
                agent_name="decomposer",
                action="plan_review",
                details={},
                status="pending",
                created_at="2026-07-30T00:00:00Z",
                decided_at=None,
                decided_by=None,
            )

            # Simulate: Repo B becomes the globally active repo AFTER Task 1
            # was created (against Repo A) but BEFORE its decision is
            # dispatched — the exact race window this fix closes.
            import app.api.repo as repo_module

            original_active = repo_module._active_repo_path
            repo_module._active_repo_path = repo_b.local_path
            try:
                with patch(
                    "app.api.agents.resume_planning_pipeline",
                    new=AsyncMock(return_value=None),
                ) as mock_resume:
                    from app.api.approvals import _dispatch_decision

                    await _dispatch_decision(row, approved=True)

                    mock_resume.assert_awaited_once()
                    _, kwargs = mock_resume.call_args
                    assert kwargs["task_id"] == task.id
                    assert kwargs["repo_path"] == repo_a.local_path, (
                        "must resolve Task 1's own repo (A), not whichever "
                        "repo is globally active at dispatch time (B)"
                    )
            finally:
                repo_module._active_repo_path = original_active

            await session.execute(delete(DevTask).where(DevTask.id == task.id))
            await session.execute(
                delete(Repo).where(Repo.id.in_([repo_a.id, repo_b.id]))
            )
            await session.commit()
    finally:
        await engine.dispose()
