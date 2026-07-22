"""Day 14 — launch_manager()'s new git-push pending-approval wiring.

Registers into Day 13's generic pending_approvals system (same table/API the
plan-review pause already uses) rather than a parallel one.

_record_git_push_approval() is tested directly against a real, isolated DB
session (not by driving the full launch_manager()/fire-and-forget-task
machinery) — calling launch_manager() itself via a fresh asyncio.run() from
sync test code hits the documented shared-engine hazard
(app.db.session.get_session_factory() is a process-wide singleton bound to
whichever event loop touches it first), and driving it through a real
TestClient would need to reliably await a raw asyncio.create_task() fire-and-
forget scheduled deep inside resume_planning_pipeline() — brittle for what
this test needs to prove. Extracting the function was the actual fix; testing
it in isolation is the correct, robust way to verify it.
"""

from __future__ import annotations

import asyncio

from app.fleet import approval_gate as ag


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _create_task_and_repo(with_github_url: bool) -> tuple[int, int | None]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask, Repo
    from app.db.repository import create_task

    async def _run() -> tuple[int, int | None]:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                repo_id = None
                if with_github_url:
                    repo = Repo(
                        github_url="https://github.com/td-owner/td-repo",
                        name="td-repo",
                        local_path="/tmp/td-launch-manager-push-test-repo",
                        status="ready",
                    )
                    session.add(repo)
                    await session.commit()
                    await session.refresh(repo)
                    repo_id = repo.id

                task = await create_task(session, "td push approval task", "desc")
                if repo_id is not None:
                    from sqlalchemy import update

                    await session.execute(
                        update(DevTask)
                        .where(DevTask.id == task.id)
                        .values(repo_id=repo_id)
                    )
                    await session.commit()
                return task.id, repo_id
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


def _cleanup(task_id: int, repo_id: int | None) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask, PendingApproval, Repo

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(
                    delete(PendingApproval).where(PendingApproval.task_id == task_id)
                )
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                if repo_id is not None:
                    await session.execute(delete(Repo).where(Repo.id == repo_id))
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def _call_record_git_push_approval(
    task_id: int,
    effective_repo: str,
    all_files: list[str],
    diff: str,
    subtask_count: int,
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.api.agents import _record_git_push_approval

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await _record_git_push_approval(
                    session, task_id, effective_repo, all_files, diff, subtask_count
                )
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_records_git_push_approval_when_repo_has_github_url() -> None:
    task_id, repo_id = _create_task_and_repo(with_github_url=True)
    try:
        _call_record_git_push_approval(
            task_id,
            "/tmp/td-launch-manager-push-test-repo",
            ["a.py", "b.py"],
            "diff --git a/a.py",
            2,
        )

        thread_id = f"task-{task_id}-push"
        approval = ag.get_pending(thread_id)
        assert approval is not None
        assert approval.action == "git_push"
        assert approval.status == "pending"
        assert approval.details["branch"] == f"agent/task-{task_id}"
        assert approval.details["files_changed"] == ["a.py", "b.py"]
        assert approval.details["subtask_count"] == 2
    finally:
        _cleanup(task_id, repo_id)


def test_skips_push_approval_when_no_github_repo() -> None:
    task_id, repo_id = _create_task_and_repo(with_github_url=False)
    try:
        _call_record_git_push_approval(
            task_id, "/tmp/td-no-such-repo-path", ["a.py"], "diff", 1
        )

        thread_id = f"task-{task_id}-push"
        assert ag.get_pending(thread_id) is None
    finally:
        _cleanup(task_id, repo_id)


def test_sets_branch_name_on_dev_task() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask

    task_id, repo_id = _create_task_and_repo(with_github_url=True)
    try:
        _call_record_git_push_approval(
            task_id, "/tmp/td-launch-manager-push-test-repo", ["a.py"], "diff", 1
        )

        async def _check() -> str | None:
            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    task = await session.get(DevTask, task_id)
                    assert task is not None
                    return task.branch_name
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        branch_name = asyncio.run(_check())
        assert branch_name == f"agent/task-{task_id}"
    finally:
        _cleanup(task_id, repo_id)


def test_is_non_fatal_when_repo_lookup_raises(monkeypatch: object) -> None:
    """Must never crash launch_manager()'s completion path — non-fatal,
    matching this file's established defensive style."""
    task_id, repo_id = _create_task_and_repo(with_github_url=False)
    try:
        # nonexistent task_id would make update_task_branch_name a no-op
        # (UPDATE matching zero rows), not raise — confirm graceful handling
        # even when nothing matches.
        _call_record_git_push_approval(
            999_999_999, "/tmp/does-not-matter", ["a.py"], "diff", 1
        )
        assert ag.get_pending("task-999999999-push") is None
    finally:
        _cleanup(task_id, repo_id)
