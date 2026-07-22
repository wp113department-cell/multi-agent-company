"""Day 14 — approvals.py's git_push dispatch branch + the new
GET/POST /api/tasks/{id}/pr and /push endpoints.

Real DB round-trip (DevTask + Repo rows), push_and_create_pr() mocked at its
home module (app.tools.git_push_tool.push_and_create_pr) since it's already
independently tested (test_git_push_tool.py) — this file is about the
dispatch wiring and HTTP endpoints, not re-testing the push mechanics.

dispatch_git_push_decision() uses app.db.session.get_session_factory() (the
shared, process-wide engine) — by design, since it's meant to run inside
FastAPI's BackgroundTasks on the app's own already-running event loop. Calling
it via a bare asyncio.run() from sync test code hits the documented
shared-engine hazard (confirmed by running this file — 2 of 10 tests failed
with "attached to a different loop" before this fix). Every test here drives
it through a real TestClient request instead, matching the established Day
12/13 pattern: TestClient's BackgroundTasks execute synchronously as part of
the request/response cycle, on the one continuous event loop that block owns.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.tools.git_push_tool import PushResult


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _create_task_and_repo(with_github_url: bool = True) -> tuple[int, int | None]:
    from sqlalchemy import update
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
                        github_url="https://github.com/td-owner/td-repo2",
                        name="td-repo2",
                        local_path="/tmp/td-dispatch-test-repo",
                        status="ready",
                    )
                    session.add(repo)
                    await session.commit()
                    await session.refresh(repo)
                    repo_id = repo.id

                task = await create_task(session, "td dispatch task", "desc")
                values: dict[str, object] = {"branch_name": f"agent/task-{task.id}"}
                if repo_id is not None:
                    values["repo_id"] = repo_id
                await session.execute(update(DevTask).where(DevTask.id == task.id).values(**values))
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
                await session.execute(delete(PendingApproval).where(PendingApproval.task_id == task_id))
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                if repo_id is not None:
                    await session.execute(delete(Repo).where(Repo.id == repo_id))
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


def _get_task_pr_status(task_id: int) -> tuple[str | None, str]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask

    async def _run() -> tuple[str | None, str]:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                task = await session.get(DevTask, task_id)
                assert task is not None
                return task.pr_url, task.pr_status
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


def _record_git_push_pending(task_id: int) -> str:
    from app.fleet import approval_gate as ag

    thread_id = f"task-{task_id}-push"
    ag.record_pending(thread_id, "git_push", {"branch": f"agent/task-{task_id}"}, agent_name="manager", task_id=task_id)
    return thread_id


class TestDispatchGitPushDecision:
    def test_approved_success_stores_pr_url_and_pushed_status(self) -> None:
        task_id, repo_id = _create_task_and_repo(with_github_url=True)
        try:
            with patch("app.tools.git_push_tool.push_and_create_pr") as mock_push:
                mock_push.return_value = PushResult(
                    pushed=True, pr_url="https://github.com/td-owner/td-repo2/pull/9", pr_number=9,
                )
                with TestClient(app) as client:
                    resp = client.post(f"/api/tasks/{task_id}/push")
                assert resp.status_code == 200

            pr_url, pr_status = _get_task_pr_status(task_id)
            assert pr_url == "https://github.com/td-owner/td-repo2/pull/9"
            assert pr_status == "pushed"
        finally:
            _cleanup(task_id, repo_id)

    def test_approved_push_failure_stores_failed_status(self) -> None:
        task_id, repo_id = _create_task_and_repo(with_github_url=True)
        try:
            with patch("app.tools.git_push_tool.push_and_create_pr") as mock_push:
                mock_push.return_value = PushResult(pushed=False, pr_url=None, pr_number=None, error="remote rejected")
                with TestClient(app) as client:
                    resp = client.post(f"/api/tasks/{task_id}/push")
                assert resp.status_code == 200

            pr_url, pr_status = _get_task_pr_status(task_id)
            assert pr_url is None
            assert pr_status == "failed"
        finally:
            _cleanup(task_id, repo_id)

    def test_no_github_repo_stores_failed_status(self) -> None:
        task_id, repo_id = _create_task_and_repo(with_github_url=False)
        try:
            with patch("app.tools.git_push_tool.push_and_create_pr") as mock_push:
                with TestClient(app) as client:
                    resp = client.post(f"/api/tasks/{task_id}/push")
                assert resp.status_code == 200
                mock_push.assert_not_called()

            pr_url, pr_status = _get_task_pr_status(task_id)
            assert pr_url is None
            assert pr_status == "failed"
        finally:
            _cleanup(task_id, repo_id)

    def test_rejected_via_generic_approvals_endpoint_stores_failed_status(self) -> None:
        """The reject path (approved=False) is only reachable via the
        generic /api/approvals/{thread_id}/reject endpoint — /push always
        dispatches with approved=True (it's an explicit manual retry)."""
        task_id, repo_id = _create_task_and_repo(with_github_url=True)
        try:
            thread_id = _record_git_push_pending(task_id)
            with patch("app.tools.git_push_tool.push_and_create_pr") as mock_push:
                with TestClient(app) as client:
                    resp = client.post(f"/api/approvals/{thread_id}/reject")
                assert resp.status_code == 200
                mock_push.assert_not_called()

            pr_url, pr_status = _get_task_pr_status(task_id)
            assert pr_url is None
            assert pr_status == "failed"
        finally:
            _cleanup(task_id, repo_id)

    def test_unknown_task_id_does_not_raise(self) -> None:
        with patch("app.tools.git_push_tool.push_and_create_pr"):
            with TestClient(app) as client:
                resp = client.post("/api/tasks/999999999/push")
            assert resp.status_code == 404  # task lookup itself 404s before dispatch


class TestTaskPrEndpoints:
    def test_get_pr_returns_branch_and_status(self) -> None:
        task_id, repo_id = _create_task_and_repo(with_github_url=True)
        try:
            with TestClient(app) as client:
                resp = client.get(f"/api/tasks/{task_id}/pr")
            assert resp.status_code == 200
            body = resp.json()
            assert body["branchName"] == f"agent/task-{task_id}"
            assert body["prStatus"] == "none"
            assert body["prUrl"] is None
        finally:
            _cleanup(task_id, repo_id)

    def test_get_pr_404_for_unknown_task(self) -> None:
        with TestClient(app) as client:
            resp = client.get("/api/tasks/999999999/pr")
        assert resp.status_code == 404

    def test_push_endpoint_triggers_dispatch_and_returns_immediately(self) -> None:
        task_id, repo_id = _create_task_and_repo(with_github_url=True)
        try:
            with patch("app.api.approvals.dispatch_git_push_decision") as mock_dispatch:
                with TestClient(app) as client:
                    resp = client.post(f"/api/tasks/{task_id}/push")
                assert resp.status_code == 200
                assert resp.json() == {"triggered": True, "taskId": task_id}
            mock_dispatch.assert_called_once_with(task_id, True)
        finally:
            _cleanup(task_id, repo_id)

    def test_push_endpoint_400_when_no_branch_yet(self) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.repository import create_task

        async def _make_task_without_branch() -> int:
            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    task = await create_task(session, "td push no branch", "desc")
                    return task.id
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        task_id = asyncio.run(_make_task_without_branch())
        try:
            with TestClient(app) as client:
                resp = client.post(f"/api/tasks/{task_id}/push")
            assert resp.status_code == 400
        finally:
            _cleanup(task_id, None)

    def test_push_endpoint_404_for_unknown_task(self) -> None:
        with TestClient(app) as client:
            resp = client.post("/api/tasks/999999999/push")
        assert resp.status_code == 404
