"""Day 12 Part 2 — Failure Recovery Ladder: all 7 states as runnable code.

Checkpoint/Rollback are re-exports of already-existing, already-tested
fleet_checkpoint.py functions (not re-tested here beyond confirming the
re-export works). Resume/Retry/Escalate/Abort/Human Review were genuinely
missing before this file — verified by reading fleet_checkpoint.py,
agent_registry.py, and db/models.py's VALID_TRANSITIONS in full first.
"""

from __future__ import annotations

import asyncio

import pytest

from app.config import get_settings
from app.db.repository import create_task, get_task
from app.fleet import failure_ladder as fl
from app.fleet.agent_registry import get_agent_registry


def _make_task(title: str = "ladder test task") -> int:
    async def _run() -> int:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                task = await create_task(session, title, "desc")
                return task.id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _get_status(task_id: int) -> str:
    async def _run() -> str:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                task = await get_task(session, task_id)
                assert task is not None
                return str(task.status)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _delete_task(task_id: int) -> None:
    async def _run() -> None:
        from sqlalchemy import delete
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.db.models import DevTask

        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Checkpoint / Rollback / Resume
# ---------------------------------------------------------------------------


def test_checkpoint_and_resume_round_trip() -> None:
    cp_id = fl.checkpoint(
        {"progress": "step_3"}, agent_name="td_ladder_agent", task_id="td-1"
    )
    resumed = fl.resume(cp_id)
    assert resumed == {"progress": "step_3"}


def test_resume_raises_on_missing_checkpoint() -> None:
    with pytest.raises(KeyError, match="No checkpoint"):
        fl.resume("td-nonexistent-checkpoint-id")


def test_rollback_still_works_via_ladder_re_export() -> None:
    cp_id = fl.checkpoint({"v": 1}, agent_name="td_ladder_agent2", task_id="td-2")
    rolled = fl.rollback(cp_id)
    assert rolled == {"v": 1}


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


def test_should_retry_bounded_by_explicit_max() -> None:
    assert fl.should_retry(0, max_retries=3) is True
    assert fl.should_retry(2, max_retries=3) is True
    assert fl.should_retry(3, max_retries=3) is False


def test_should_retry_defaults_to_settings_max_retries() -> None:
    limit = get_settings().max_retries
    assert fl.should_retry(limit - 1) is True
    assert fl.should_retry(limit) is False


# ---------------------------------------------------------------------------
# Escalate
# ---------------------------------------------------------------------------


def test_escalate_marks_agent_error_and_increments_error_count() -> None:
    # fail_task() (which escalate() wraps) is a no-op for a name that was
    # never registered — real agents self-register via their own _register()
    # at import time, so this mirrors that: register first, same as
    # run_agent_graph()'s own exception handler assumes.
    agent_name = "td_ladder_escalate_agent"
    reg = get_agent_registry()
    reg.register(agent_name)
    before = reg.get(agent_name)
    before_count = before.error_count if before else 0

    fl.escalate(agent_name, "simulated failure", trace_id="t1")

    after = reg.get(agent_name)
    assert after is not None
    assert after.error_count == before_count + 1
    from app.fleet.agent_registry import AgentState

    assert after.state == AgentState.ERROR


def test_escalate_is_non_fatal_on_publish_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.fleet.fleet_events as fleet_events_module

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("event bus down")

    monkeypatch.setattr(fleet_events_module, "publish", _boom)
    fl.escalate("td_ladder_escalate_agent_2", "reason", trace_id="")  # must not raise


# ---------------------------------------------------------------------------
# Abort
# ---------------------------------------------------------------------------


def test_abort_transitions_task_to_failed() -> None:
    task_id = _make_task()
    try:
        result = fl.abort(str(task_id), "unrecoverable error", trace_id="t1")
        assert result is True
        assert _get_status(task_id) == "failed"
    finally:
        _delete_task(task_id)


def test_abort_with_none_task_id_is_a_safe_no_op() -> None:
    assert fl.abort(None, "no task to abort", trace_id="") is False


def test_abort_with_nonexistent_task_id_returns_false_not_raise() -> None:
    assert fl.abort("999999999", "reason", trace_id="") is False


# ---------------------------------------------------------------------------
# Human Review
# ---------------------------------------------------------------------------


def test_request_human_review_transitions_task_to_blocked() -> None:
    task_id = _make_task()
    try:
        result = fl.request_human_review(
            str(task_id), "td_agent", "stall detected", trace_id="t1"
        )
        assert result is True
        assert _get_status(task_id) == "blocked"
    finally:
        _delete_task(task_id)


def test_request_human_review_with_none_task_id_is_a_safe_no_op() -> None:
    assert fl.request_human_review(None, "td_agent", "reason", trace_id="") is False


# ---------------------------------------------------------------------------
# VALID_TRANSITIONS gap closed
# ---------------------------------------------------------------------------


def test_failed_is_now_reachable_from_every_in_progress_status() -> None:
    from app.db.models import can_transition

    for status in (
        "pending",
        "planning",
        "ready_for_review",
        "coding",
        "testing",
        "blocked",
    ):
        assert can_transition(status, "failed"), f"{status} -> failed should be valid"


# ---------------------------------------------------------------------------
# run_manager() wiring — escalate/request_human_review on a single subtask's
# retry exhaustion; abort on a whole-epic halt. run_manager() already had a
# real, tested bounded retry loop (max_retries per subtask) — this reuses
# that existing mechanism rather than adding a second retry loop inside
# base_graph.py's hot path (shared by all 72+ agents).
# ---------------------------------------------------------------------------


def test_run_manager_calls_escalate_and_human_review_when_subtask_blocked() -> None:
    from unittest.mock import patch

    from app.agents.manager import run_manager
    from app.agents.qa import QAResult

    with patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev, patch(
        "app.agents.qa.run_qa"
    ) as mock_qa, patch("app.fleet.failure_ladder.escalate") as mock_escalate, patch(
        "app.fleet.failure_ladder.request_human_review"
    ) as mock_human_review, patch(
        "app.services.git_service.git_add"
    ) as mock_git_add, patch("app.services.git_service.git_commit") as mock_git_commit:
        mock_backend_dev.return_value = (["app/api/hello.py"], None)
        mock_git_add.return_value = {"ok": True, "stdout": "", "stderr": ""}
        mock_git_commit.return_value = {"ok": True, "stdout": "", "stderr": ""}
        mock_qa.return_value = QAResult(
            status="failed",
            tests_run=3,
            tests_passed=0,
            tests_failed=3,
            typecheck_clean=False,
            lint_clean=False,
            errors=["always fails"],
            summary="failing",
        )

        result = asyncio.run(
            run_manager(
                task_id=999_101,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "x", "description": "y"}
                ],
                worktree_path="/tmp/does-not-need-to-exist",
                plan="plan",
                repo_path="/home/pc-117/Documents/CRR2906",
            )
        )

    assert result["status"] == "blocked"
    assert result["results"][0]["status"] == "blocked"
    mock_escalate.assert_called_once()
    mock_human_review.assert_called_once()
    assert mock_escalate.call_args.args[0] == "manager"


def test_run_manager_calls_abort_when_epic_halted() -> None:
    from unittest.mock import patch

    from app.agents.manager import run_manager
    from app.agents.qa import QAResult

    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    max_epic_failures = settings.manager_max_epic_failures

    subtasks = [
        {"id": i, "type": "backend", "title": f"subtask {i}", "description": "y"}
        for i in range(1, max_epic_failures + 1)
    ]

    with patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev, patch(
        "app.agents.qa.run_qa"
    ) as mock_qa, patch("app.fleet.failure_ladder.abort") as mock_abort, patch(
        "app.services.git_service.git_add"
    ) as mock_git_add, patch("app.services.git_service.git_commit") as mock_git_commit:
        mock_backend_dev.return_value = (["app/api/hello.py"], None)
        mock_git_add.return_value = {"ok": True, "stdout": "", "stderr": ""}
        mock_git_commit.return_value = {"ok": True, "stdout": "", "stderr": ""}
        mock_qa.return_value = QAResult(
            status="failed",
            tests_run=1,
            tests_passed=0,
            tests_failed=1,
            typecheck_clean=False,
            lint_clean=False,
            errors=["always fails"],
            summary="failing",
        )

        result = asyncio.run(
            run_manager(
                task_id=999_102,
                subtasks=subtasks,
                worktree_path="/tmp/does-not-need-to-exist",
                plan="plan",
                repo_path="/home/pc-117/Documents/CRR2906",
            )
        )

    assert result["status"] == "halted"
    mock_abort.assert_called_once()
    assert mock_abort.call_args.args[0] == "999102"
