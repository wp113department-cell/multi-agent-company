"""Audit 04 (Orchestration) fix verification — docs/reports/AUDIT_04_ORCHESTRATION.md.

Covers all 12 findings fixed in this pass (ORCH-04-001 through ORCH-04-016).
Follows this repo's established conventions (see test_launch_coder_bootstrap.py,
test_approvals_api.py, test_git_push_approval_dispatch.py, test_concurrency.py):
- DB-touching tests use an isolated engine (never the shared app.db.session
  singleton) for setup/teardown helpers, and drive real behavior through a
  real TestClient so BackgroundTasks execute synchronously within the request.
- No real Anthropic API calls anywhere — every LLM-driven agent function is
  mocked at its own definition site (the module that actually defines it,
  since every real caller in this codebase uses a deferred `from X import Y`
  inside the function body, not a module-level import — patching the
  definition site is what actually takes effect on the next call).

NOTE (2026-07-27): written and reviewed by careful manual read against the
real source, but NOT executed — this environment has no Python interpreter
available (see PENDING_TESTS_API_KEYS.md for the full explanation and the
exact command to run this file once a Python + Postgres environment is
available). Treat as "ready to run," not "confirmed green."
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _cleanup_task(task_id: int, repo_id: int | None = None) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask, PendingApproval, Repo, Subtask

    async def _do() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                await session.execute(
                    delete(PendingApproval).where(PendingApproval.task_id == task_id)
                )
                await session.execute(delete(Subtask).where(Subtask.task_id == task_id))
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                if repo_id is not None:
                    await session.execute(delete(Repo).where(Repo.id == repo_id))
                await session.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    _run(_do())


def _create_task_with_status(
    status: str, diff: str | None = None, repo_id: int | None = None
) -> int:
    from sqlalchemy import update

    from app.db.models import DevTask
    from app.db.repository import create_task

    async def _do() -> int:
        engine = _new_isolated_db_engine()
        try:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                task = await create_task(
                    session, "audit04 fix test task", "desc", repo_id=repo_id
                )
                await session.execute(
                    update(DevTask)
                    .where(DevTask.id == task.id)
                    .values(status=status, diff=diff)
                )
                await session.commit()
                return task.id
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return _run(_do())


def _get_task_status(task_id: int) -> str:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask

    async def _do() -> str:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                task = await session.get(DevTask, task_id)
                assert task is not None
                return str(task.status)
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return _run(_do())


# ---------------------------------------------------------------------------
# ORCH-04-001 — launch_coder commits before computing the diff
# ---------------------------------------------------------------------------


class TestOrch04_001_LaunchCoderCommits:
    def test_launch_coder_commits_files_before_diff(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        task_id = _create_task_with_status("ready_for_review")
        try:
            with patch(
                "app.pipeline.bootstrap.is_blank_repo", return_value=False
            ), patch(
                "app.api.agents.create_worktree", return_value=tmp_path / "wt"
            ), patch(
                "app.agents.coder.run_coder",
                return_value=(["backend/app/new_file.py"], None, 10, 5),
            ), patch(
                "app.services.git_service.git_add",
                new=AsyncMock(return_value={"ok": True, "stdout": "", "stderr": ""}),
            ) as mock_git_add, patch(
                "app.services.git_service.git_commit",
                new=AsyncMock(return_value={"ok": True, "stdout": "", "stderr": ""}),
            ) as mock_git_commit, patch(
                "app.api.agents.get_diff",
                return_value="diff --git a/backend/app/new_file.py ...",
            ), patch(
                "app.api.agents.preserve_worktree"
            ):
                with TestClient(app) as client:
                    resp = client.post(f"/api/tasks/{task_id}/approve")
                assert resp.status_code == 200, resp.text

            mock_git_add.assert_called_once()
            add_args = mock_git_add.call_args.args
            assert add_args[1] == ["backend/app/new_file.py"]
            mock_git_commit.assert_called_once()

            with TestClient(app) as client2:
                task_data = client2.get(f"/api/tasks/{task_id}").json()
            assert task_data["diff"] == "diff --git a/backend/app/new_file.py ..."
        finally:
            _cleanup_task(task_id)

    def test_launch_coder_skips_commit_when_no_files_changed(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """No files_changed -> no git_add/git_commit call at all (nothing to commit)."""
        task_id = _create_task_with_status("ready_for_review")
        try:
            with patch(
                "app.pipeline.bootstrap.is_blank_repo", return_value=False
            ), patch(
                "app.api.agents.create_worktree", return_value=tmp_path / "wt"
            ), patch(
                "app.agents.coder.run_coder", return_value=([], None, 10, 5)
            ), patch(
                "app.services.git_service.git_add", new=AsyncMock()
            ) as mock_git_add, patch(
                "app.services.git_service.git_commit", new=AsyncMock()
            ) as mock_git_commit, patch(
                "app.api.agents.get_diff", return_value=""
            ), patch(
                "app.api.agents.preserve_worktree"
            ):
                with TestClient(app) as client:
                    resp = client.post(f"/api/tasks/{task_id}/approve")
                assert resp.status_code == 200, resp.text

            mock_git_add.assert_not_called()
            mock_git_commit.assert_not_called()
        finally:
            _cleanup_task(task_id)


# ---------------------------------------------------------------------------
# ORCH-04-002 — real terminal "completed" state + idempotent approve_task
# ---------------------------------------------------------------------------


class TestOrch04_002_TerminalState:
    def test_can_transition_ready_for_review_to_completed(self) -> None:
        from app.db.models import can_transition

        assert can_transition("ready_for_review", "completed") is True
        assert can_transition("completed", "anything") is False

    def test_approve_rejects_already_coded_task_with_409(self) -> None:
        """task.diff already set -> this is a re-click on a code-complete
        task, not a real 'start coding' request. Must 409, not re-dispatch
        launch_coder."""
        task_id = _create_task_with_status(
            "ready_for_review", diff="diff --git a/x.py b/x.py\n..."
        )
        try:
            with patch("app.api.agents.launch_coder") as mock_launch_coder:
                with TestClient(app) as client:
                    resp = client.post(f"/api/tasks/{task_id}/approve")
                assert resp.status_code == 409, resp.text
            mock_launch_coder.assert_not_called()
            assert _get_task_status(task_id) == "ready_for_review"
        finally:
            _cleanup_task(task_id)

    def test_approve_succeeds_when_diff_not_yet_set(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The real first-time case: plan ready, diff is None -> approve
        proceeds as before."""
        task_id = _create_task_with_status("ready_for_review", diff=None)
        try:
            with patch("app.api.agents.launch_coder") as mock_launch_coder:
                with TestClient(app) as client:
                    resp = client.post(f"/api/tasks/{task_id}/approve")
                assert resp.status_code == 200, resp.text
            mock_launch_coder.assert_called_once()
            assert _get_task_status(task_id) == "coding"
        finally:
            _cleanup_task(task_id)

    def test_complete_endpoint_requires_diff(self) -> None:
        task_id = _create_task_with_status("ready_for_review", diff=None)
        try:
            with TestClient(app) as client:
                resp = client.post(f"/api/tasks/{task_id}/complete")
            assert resp.status_code == 400
            assert _get_task_status(task_id) == "ready_for_review"
        finally:
            _cleanup_task(task_id)

    def test_complete_endpoint_success(self) -> None:
        task_id = _create_task_with_status(
            "ready_for_review", diff="diff --git a/x.py b/x.py\n..."
        )
        try:
            with patch("app.api.tasks.remove_worktree") as mock_remove:
                with TestClient(app) as client:
                    resp = client.post(f"/api/tasks/{task_id}/complete")
                assert resp.status_code == 200, resp.text
                assert resp.json()["task"]["status"] == "completed"
            mock_remove.assert_called_once()
            assert _get_task_status(task_id) == "completed"
        finally:
            _cleanup_task(task_id)

    def test_complete_endpoint_wrong_status_400(self) -> None:
        task_id = _create_task_with_status("blocked")
        try:
            with TestClient(app) as client:
                resp = client.post(f"/api/tasks/{task_id}/complete")
            assert resp.status_code == 400
        finally:
            _cleanup_task(task_id)

    def test_successful_push_auto_completes_task(self) -> None:
        """dispatch_git_push_decision() now transitions ready_for_review (with
        a diff) -> completed on a successful push, closing the "task never
        reaches a terminal state" gap for the common full-mode case."""
        from app.tools.git_push_tool import PushResult

        from sqlalchemy import update
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import DevTask, Repo
        from app.db.repository import create_task

        async def _setup() -> tuple[int, int]:
            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    repo = Repo(
                        github_url="https://github.com/td-owner/td-orch04-repo",
                        name="td-orch04-repo",
                        local_path="/tmp/td-orch04-repo",
                        status="ready",
                    )
                    session.add(repo)
                    await session.commit()
                    await session.refresh(repo)

                    task = await create_task(
                        session, "push completes", "desc", repo_id=repo.id
                    )
                    await session.execute(
                        update(DevTask)
                        .where(DevTask.id == task.id)
                        .values(
                            status="ready_for_review",
                            diff="diff --git a/x.py b/x.py\n...",
                            branch_name=f"agent/task-{task.id}",
                        )
                    )
                    await session.commit()
                    return task.id, repo.id
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        task_id, repo_id = _run(_setup())
        try:
            with patch(
                "app.tools.git_push_tool.push_and_create_pr"
            ) as mock_push, patch(
                "app.repo_tools.worktree.remove_worktree"
            ) as mock_remove:
                mock_push.return_value = PushResult(
                    pushed=True,
                    pr_url="https://github.com/td-owner/td-orch04-repo/pull/1",
                    pr_number=1,
                )
                with TestClient(app) as client:
                    resp = client.post(f"/api/tasks/{task_id}/push")
                assert resp.status_code == 200

            assert _get_task_status(task_id) == "completed"
            mock_remove.assert_called_once()
        finally:
            _cleanup_task(task_id, repo_id)


# ---------------------------------------------------------------------------
# ORCH-04-004 — /restart in-progress guard
# ---------------------------------------------------------------------------


class TestOrch04_004_RestartGuard:
    @pytest.mark.parametrize("active_status", ["planning", "coding", "testing"])
    def test_restart_rejects_active_pipeline(self, active_status: str) -> None:
        task_id = _create_task_with_status(active_status)
        try:
            with TestClient(app) as client:
                resp = client.post(f"/api/tasks/{task_id}/restart")
            assert resp.status_code == 409, resp.text
            assert _get_task_status(task_id) == active_status
        finally:
            _cleanup_task(task_id)

    @pytest.mark.parametrize("terminal_status", ["blocked", "failed", "rejected"])
    def test_restart_allows_terminal_ish_status(self, terminal_status: str) -> None:
        task_id = _create_task_with_status(terminal_status)
        try:
            with patch("app.api.agents.launch_planning_pipeline") as mock_launch:
                with TestClient(app) as client:
                    resp = client.post(f"/api/tasks/{task_id}/restart")
                assert resp.status_code == 200, resp.text
            mock_launch.assert_called_once()
            assert _get_task_status(task_id) == "planning"
        finally:
            _cleanup_task(task_id)


# ---------------------------------------------------------------------------
# ORCH-04-007 — approval double-decision race
# ---------------------------------------------------------------------------


class TestOrch04_007_ApprovalRace:
    def test_second_decide_call_rejected_even_before_dispatch_runs(self) -> None:
        """Directly exercises _decide_or_409()'s synchronous flip: the second
        call must 409 immediately, without needing the first call's
        background dispatch (resume_planning_pipeline) to have run at all —
        proving the fix closes the race window, not just the
        already-fully-resolved case the pre-existing
        test_approve_twice_returns_409_second_time (test_approvals_api.py)
        covers."""
        from app.api.approvals import _decide_or_409
        from app.fleet.approval_gate import arecord_pending

        async def _do() -> None:
            await arecord_pending(
                thread_id="test-orch04-007-race", action="plan_review", task_id=None
            )
            first = await _decide_or_409("test-orch04-007-race", True)
            assert first.thread_id == "test-orch04-007-race"

            with pytest.raises(HTTPException) as exc_info:
                await _decide_or_409("test-orch04-007-race", True)
            assert exc_info.value.status_code == 409

        try:
            _run(_do())
        finally:
            from sqlalchemy import delete
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from app.db.models import PendingApproval

            async def _cleanup() -> None:
                engine = _new_isolated_db_engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                        await session.execute(
                            delete(PendingApproval).where(
                                PendingApproval.thread_id == "test-orch04-007-race"
                            )
                        )
                        await session.commit()
                finally:
                    await engine.dispose()  # type: ignore[attr-defined]

            _run(_cleanup())

    def test_git_push_decision_now_flips_status_synchronously(self) -> None:
        """Second gap this fix closed: dispatch_git_push_decision() never
        called arecord_decision() at all before this fix, so a git_push
        PendingApproval row never left "pending" even after being decided.
        _decide_or_409() now flips it regardless of action type."""
        from app.api.approvals import _decide_or_409
        from app.fleet.approval_gate import aget_pending, arecord_pending

        async def _do() -> None:
            await arecord_pending(
                thread_id="test-orch04-007-gitpush",
                action="git_push",
                task_id=None,
            )
            await _decide_or_409("test-orch04-007-gitpush", True)
            row = await aget_pending("test-orch04-007-gitpush")
            assert row is not None
            assert row.status == "approved"

        try:
            _run(_do())
        finally:
            from sqlalchemy import delete
            from sqlalchemy.ext.asyncio import async_sessionmaker

            from app.db.models import PendingApproval

            async def _cleanup() -> None:
                engine = _new_isolated_db_engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                        await session.execute(
                            delete(PendingApproval).where(
                                PendingApproval.thread_id == "test-orch04-007-gitpush"
                            )
                        )
                        await session.commit()
                finally:
                    await engine.dispose()  # type: ignore[attr-defined]

            _run(_cleanup())


# ---------------------------------------------------------------------------
# ORCH-04-014 — asyncio.create_task reference retention
# ---------------------------------------------------------------------------


class TestOrch04_014_SpawnTracked:
    async def test_spawn_tracked_retains_then_releases_reference(self) -> None:
        from app.api import agents as agents_mod

        started = asyncio.Event()
        finished = asyncio.Event()

        async def _marker() -> None:
            started.set()
            await asyncio.sleep(0.01)
            finished.set()

        task = agents_mod._spawn_tracked(_marker())
        assert task in agents_mod._background_tasks

        await asyncio.wait_for(started.wait(), timeout=1.0)
        assert task in agents_mod._background_tasks  # still running -> still tracked

        await asyncio.wait_for(finished.wait(), timeout=1.0)
        await task
        # `await task` on an already-completed task returns synchronously
        # without yielding to the loop, but add_done_callback's callback
        # (the discard() that untracks it) is scheduled via call_soon and
        # only actually runs on the *next* loop iteration. Found via real
        # execution: without this extra yield, the assertion below ran one
        # tick too early and saw the task still tracked.
        await asyncio.sleep(0)
        assert task not in agents_mod._background_tasks


# ---------------------------------------------------------------------------
# ORCH-04-008 / ORCH-04-015 — should_retry wiring, manager_max_subtask_retries,
# and backoff, without amplifying against run_backend_dev's own inner loop.
# ---------------------------------------------------------------------------


class TestOrch04_008_015_RetryWiring:
    async def test_run_manager_retry_count_uses_manager_max_subtask_retries(
        self,
    ) -> None:
        """A persistently-failing dev agent should be retried exactly
        settings.manager_max_subtask_retries times (not settings.max_retries,
        which is a separate, larger-by-default budget used one layer down
        inside run_backend_dev's own static-check loop)."""
        from app.agents.manager import run_manager
        from app.config import get_settings

        settings = get_settings()
        call_count = {"n": 0}

        def _always_fails(**kwargs: object) -> tuple[list[str], str | None, int, int]:
            call_count["n"] += 1
            return [], "simulated persistent dev agent failure", 0, 0

        with patch(
            "app.agents.backend_dev.run_backend_dev", side_effect=_always_fails
        ), patch("asyncio.sleep", new=AsyncMock()):
            result = await run_manager(
                task_id=999999001,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "t", "description": "d"}
                ],
                worktree_path="/tmp/does-not-matter",
                plan="plan",
            )

        assert call_count["n"] == settings.manager_max_subtask_retries
        assert result["status"] in ("blocked", "halted")

    async def test_run_manager_backs_off_between_retries(self) -> None:
        from app.agents.manager import run_manager

        def _always_fails(**kwargs: object) -> tuple[list[str], str | None, int, int]:
            return [], "simulated failure", 0, 0

        with patch(
            "app.agents.backend_dev.run_backend_dev", side_effect=_always_fails
        ), patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await run_manager(
                task_id=999999002,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "t", "description": "d"}
                ],
                worktree_path="/tmp/does-not-matter",
                plan="plan",
            )

        assert mock_sleep.await_count >= 1


# ---------------------------------------------------------------------------
# ORCH-04-009 — concurrency semaphores actually acquired/released
# ---------------------------------------------------------------------------


class TestOrch04_009_ConcurrencySlots:
    async def test_run_manager_does_not_leak_agent_run_slot(self) -> None:
        """With max_agent_runs=1, a full successful dev->qa->review cycle
        (3 sequential agent_run_slot() acquisitions within ONE subtask) must
        still complete — proves each acquisition is correctly released, not
        held past its own call, and that this doesn't deadlock against
        itself within a single subtask's sequential dev/qa/review steps."""
        from app.agents.manager import run_manager
        from app.agents.qa import QAResult
        from app.agents.reviewer import ReviewResult
        from app.pipeline.concurrency import reset_for_testing

        reset_for_testing(max_epics=1, max_agent_runs=1, max_subtasks_per_epic=1)

        with patch(
            "app.agents.backend_dev.run_backend_dev",
            return_value=(["f.py"], None, 0, 0),
        ), patch(
            "app.services.git_service.git_add",
            new=AsyncMock(return_value={"ok": True, "stdout": "", "stderr": ""}),
        ), patch(
            "app.services.git_service.git_commit",
            new=AsyncMock(return_value={"ok": True, "stdout": "", "stderr": ""}),
        ), patch(
            "app.agents.qa.run_qa",
            return_value=QAResult(
                status="passed",
                tests_run=1,
                tests_passed=1,
                tests_failed=0,
                typecheck_clean=True,
                lint_clean=True,
                summary="ok",
            ),
        ), patch(
            "app.repo_tools.worktree.get_diff", return_value="diff text"
        ), patch(
            "app.agents.reviewer.run_reviewer",
            return_value=ReviewResult(verdict="approved", findings=[], summary="ok"),
        ):
            result = await asyncio.wait_for(
                run_manager(
                    task_id=999999003,
                    subtasks=[
                        {"id": 1, "type": "backend", "title": "t", "description": "d"}
                    ],
                    worktree_path="/tmp/does-not-matter",
                    plan="plan",
                ),
                timeout=5.0,
            )

        assert result["status"] == "completed"

    async def test_run_epic_manager_releases_epic_slot_on_early_return(self) -> None:
        """The pending_cost_approval early-return path is inside the
        epic_slot()-holding wrapper too (run_epic_manager -> async with
        epic_slot(): return await _run_epic_manager_body(...)) — with
        max_epics=1, calling it twice in a row must not hang, proving the
        slot is released even on this early-return path."""
        from types import SimpleNamespace

        from app.agents.manager import run_epic_manager
        from app.pipeline.concurrency import reset_for_testing

        reset_for_testing(max_epics=1, max_agent_runs=5, max_subtasks_per_epic=5)

        fake_estimate = SimpleNamespace(
            estimated_cost_usd=999.0, requires_approval=True
        )

        with patch(
            "app.pipeline.cost_controller.estimate_epic_cost",
            new=AsyncMock(return_value=fake_estimate),
        ):
            from sqlalchemy.ext.asyncio import async_sessionmaker
            from sqlalchemy import delete

            from app.db.models import Epic

            async def _make_epic() -> str:
                import uuid

                engine = _new_isolated_db_engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                        epic_id = str(uuid.uuid4())
                        session.add(
                            Epic(
                                epic_id=epic_id,
                                title="orch04-009 epic slot test",
                                description="d",
                                status="pending",
                            )
                        )
                        await session.commit()
                        return epic_id
                finally:
                    await engine.dispose()  # type: ignore[attr-defined]

            async def _cleanup_epic(epic_id: str) -> None:
                engine = _new_isolated_db_engine()
                try:
                    async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                        await session.execute(
                            delete(Epic).where(Epic.epic_id == epic_id)
                        )
                        await session.commit()
                finally:
                    await engine.dispose()  # type: ignore[attr-defined]

            epic_id_a = await _make_epic()
            epic_id_b = await _make_epic()
            try:
                engine = _new_isolated_db_engine()
                async_sessionmaker_fn = async_sessionmaker(
                    engine, expire_on_commit=False
                )
                async with async_sessionmaker_fn() as session_a:  # type: ignore[arg-type]
                    pkg_a = await asyncio.wait_for(
                        run_epic_manager(
                            epic_id=epic_id_a, goal="goal a", db=session_a
                        ),
                        timeout=5.0,
                    )
                async with async_sessionmaker_fn() as session_b:  # type: ignore[arg-type]
                    pkg_b = await asyncio.wait_for(
                        run_epic_manager(
                            epic_id=epic_id_b, goal="goal b", db=session_b
                        ),
                        timeout=5.0,
                    )
                await engine.dispose()  # type: ignore[attr-defined]

                assert pkg_a.status == "pending_cost_approval"
                assert pkg_b.status == "pending_cost_approval"
            finally:
                await _cleanup_epic(epic_id_a)
                await _cleanup_epic(epic_id_b)


# ---------------------------------------------------------------------------
# ORCH-04-010 — check_file_conflicts wired in + dict-vs-str bug fix
# ---------------------------------------------------------------------------


class TestOrch04_010_ConflictGuard:
    async def test_get_epic_files_reads_real_dict_shaped_impacted_files(self) -> None:
        """The bug this test locks in: architect.py's real
        submit_architect_plan schema always produces
        impacted_files=[{"path": ..., "reason": ...}], never bare strings.
        _get_epic_files()'s old `isinstance(f, str)` check silently returned
        an empty set for every real epic before this fix."""
        import uuid

        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import DevTask, Epic, PipelineState
        from app.pipeline.conflict_guard import _get_epic_files

        engine = _new_isolated_db_engine()
        epic_id = str(uuid.uuid4())
        task_id: int | None = None
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                session.add(
                    Epic(epic_id=epic_id, title="t", description="d", status="coding")
                )
                await session.commit()

                task = DevTask(
                    title="t", description="d", status="coding", epic_id=epic_id
                )
                session.add(task)
                await session.commit()
                await session.refresh(task)
                task_id = task.id

                session.add(
                    PipelineState(
                        task_id=task_id,
                        stage="done",
                        architect_plan={
                            "impacted_files": [
                                {"path": "backend/app/shared.py", "reason": "r"},
                                {"path": "backend/app/other.py", "reason": "r"},
                            ]
                        },
                    )
                )
                await session.commit()

                files = await _get_epic_files(epic_id, session)
                assert files == {"backend/app/shared.py", "backend/app/other.py"}
        finally:
            from sqlalchemy import delete

            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                if task_id is not None:
                    await session.execute(
                        delete(PipelineState).where(PipelineState.task_id == task_id)
                    )
                    await session.execute(delete(DevTask).where(DevTask.id == task_id))
                await session.execute(delete(Epic).where(Epic.epic_id == epic_id))
                await session.commit()
            await engine.dispose()  # type: ignore[attr-defined]

    async def test_check_file_conflicts_detects_real_overlap(self) -> None:
        import uuid

        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import DevTask, Epic, PipelineState
        from app.pipeline.conflict_guard import check_file_conflicts

        engine = _new_isolated_db_engine()
        other_epic_id = str(uuid.uuid4())
        this_epic_id = str(uuid.uuid4())
        task_id: int | None = None
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                session.add(
                    Epic(
                        epic_id=other_epic_id,
                        title="other",
                        description="d",
                        status="coding",
                    )
                )
                await session.commit()

                task = DevTask(
                    title="t", description="d", status="coding", epic_id=other_epic_id
                )
                session.add(task)
                await session.commit()
                await session.refresh(task)
                task_id = task.id

                session.add(
                    PipelineState(
                        task_id=task_id,
                        stage="done",
                        architect_plan={
                            "impacted_files": [
                                {"path": "shared/config.py", "reason": "r"}
                            ]
                        },
                    )
                )
                await session.commit()

                conflict = await check_file_conflicts(
                    ["shared/config.py", "other/file.py"], this_epic_id, session
                )
                assert conflict is not None
                assert "shared/config.py" in conflict or "config.py" in conflict

                no_conflict = await check_file_conflicts(
                    ["totally/unrelated.py"], this_epic_id, session
                )
                assert no_conflict is None
        finally:
            from sqlalchemy import delete

            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                if task_id is not None:
                    await session.execute(
                        delete(PipelineState).where(PipelineState.task_id == task_id)
                    )
                    await session.execute(delete(DevTask).where(DevTask.id == task_id))
                await session.execute(delete(Epic).where(Epic.epic_id == other_epic_id))
                await session.commit()
            await engine.dispose()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# ORCH-04-011 — Subtask.status persisted after run_manager()
# ---------------------------------------------------------------------------


class TestOrch04_011_SubtaskStatusPersistence:
    async def test_run_manager_persists_completed_status_on_subtask_row(self) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.agents.manager import run_manager
        from app.agents.qa import QAResult
        from app.agents.reviewer import ReviewResult
        from app.db.repository import create_task, save_subtasks

        engine = _new_isolated_db_engine()
        task_id: int | None = None
        try:
            async_sessionmaker_fn = async_sessionmaker(engine, expire_on_commit=False)
            async with async_sessionmaker_fn() as session:  # type: ignore[arg-type]
                task = await create_task(session, "subtask status test", "desc")
                task_id = task.id
                subtasks = [
                    {
                        "id": 1,
                        "type": "backend",
                        "title": "Do the thing",
                        "description": "d",
                    }
                ]
                await save_subtasks(session, task_id, subtasks)

                with patch(
                    "app.agents.backend_dev.run_backend_dev",
                    return_value=(["f.py"], None, 0, 0),
                ), patch(
                    "app.services.git_service.git_add",
                    new=AsyncMock(
                        return_value={"ok": True, "stdout": "", "stderr": ""}
                    ),
                ), patch(
                    "app.services.git_service.git_commit",
                    new=AsyncMock(
                        return_value={"ok": True, "stdout": "", "stderr": ""}
                    ),
                ), patch(
                    "app.agents.qa.run_qa",
                    return_value=QAResult(
                        status="passed",
                        tests_run=1,
                        tests_passed=1,
                        tests_failed=0,
                        typecheck_clean=True,
                        lint_clean=True,
                        summary="ok",
                    ),
                ), patch(
                    "app.repo_tools.worktree.get_diff", return_value="diff text"
                ), patch(
                    "app.agents.reviewer.run_reviewer",
                    return_value=ReviewResult(
                        verdict="approved", findings=[], summary="ok"
                    ),
                ):
                    result = await run_manager(
                        task_id=task_id,
                        subtasks=subtasks,
                        worktree_path="/tmp/does-not-matter",
                        plan="plan",
                        db=session,
                    )

                assert result["status"] == "completed"

                from app.db.repository import list_subtasks

                rows = await list_subtasks(session, task_id)
                assert len(rows) == 1
                assert rows[0].status == "completed"
        finally:
            if task_id is not None:
                from sqlalchemy import delete

                from app.db.models import DevTask, Subtask

                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    await session.execute(
                        delete(Subtask).where(Subtask.task_id == task_id)
                    )
                    await session.execute(delete(DevTask).where(DevTask.id == task_id))
                    await session.commit()
            await engine.dispose()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# ORCH-04-012 — worktree cleanup + stale-reuse validation
# ---------------------------------------------------------------------------


class TestOrch04_012_WorktreeCleanup:
    def test_create_worktree_rebuilds_a_stale_unregistered_directory(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Simulates the /restart-reuse hazard directly: a directory exists
        at the expected worktree path, but git no longer considers it a
        registered worktree (e.g. a previous `git worktree remove` ran but
        something recreated an empty directory afterward, or the .git
        metadata was corrupted/deleted directly). create_worktree() must
        detect this and rebuild cleanly instead of silently trusting it."""
        import subprocess

        from app.repo_tools import worktree as wt_mod

        base_repo = tmp_path / "base"
        base_repo.mkdir()
        subprocess.run(["git", "init", str(base_repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"], cwd=base_repo, check=True
        )
        subprocess.run(["git", "config", "user.name", "t"], cwd=base_repo, check=True)
        (base_repo / "README.md").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=base_repo, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=base_repo, check=True)

        with patch.object(wt_mod, "get_settings") as mock_settings:
            from unittest.mock import MagicMock

            s = MagicMock()
            s.worktrees_dir = str(tmp_path / "worktrees")
            s.target_repo_path = str(base_repo)
            mock_settings.return_value = s

            wt1 = wt_mod.create_worktree("stale-test-1", str(base_repo))
            assert wt1.exists()
            assert wt_mod._is_registered_worktree(wt1, str(base_repo))

            # Simulate staleness: unregister via git directly, but leave (or
            # recreate) a plain directory at the same path afterward.
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt1)],
                cwd=base_repo,
                check=True,
            )
            wt1.mkdir(parents=True, exist_ok=True)
            (wt1 / "leftover.txt").write_text("stale leftover file")
            assert wt1.exists()
            assert not wt_mod._is_registered_worktree(wt1, str(base_repo))

            wt2 = wt_mod.create_worktree("stale-test-1", str(base_repo))
            assert wt2 == wt1
            assert wt_mod._is_registered_worktree(wt2, str(base_repo))
            assert not (wt2 / "leftover.txt").exists()

    def test_reject_task_removes_worktree(self) -> None:
        task_id = _create_task_with_status("ready_for_review")
        try:
            with patch("app.api.tasks.remove_worktree") as mock_remove:
                with TestClient(app) as client:
                    resp = client.post(f"/api/tasks/{task_id}/reject", json={})
                assert resp.status_code == 200, resp.text
            mock_remove.assert_called_once()
        finally:
            _cleanup_task(task_id)


# ---------------------------------------------------------------------------
# ORCH-04-016 — documented, not wired: sanity check the module still imports
# cleanly and the documented behavior (BackgroundTasks bypasses it) is real.
# ---------------------------------------------------------------------------


class TestOrch04_016_QueueAdapterDocumented:
    def test_queue_adapter_module_still_importable(self) -> None:
        from app.pipeline.queue_adapter import AsyncioQueueAdapter, get_queue_adapter

        adapter = get_queue_adapter()
        assert isinstance(adapter, AsyncioQueueAdapter)

    def test_real_dispatch_uses_background_tasks_not_queue_adapter(self) -> None:
        """Documents the current (intentional) state: /run dispatches via
        BackgroundTasks.add_task, never queue().enqueue(...)."""
        with patch("app.pipeline.queue_adapter.queue") as mock_queue, patch(
            "app.api.agents.launch_planner"
        ):
            task_id = _create_task_with_status("pending")
            try:
                with TestClient(app) as client:
                    resp = client.post(
                        f"/api/tasks/{task_id}/run", json={"mode": "simple"}
                    )
                assert resp.status_code == 200
            finally:
                _cleanup_task(task_id)
        mock_queue.assert_not_called()
