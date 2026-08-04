"""Tests for MASTER_AGENT_v2.md Phase 1.1 — universal memory write hook.

Before app/memory/hooks.py existed, embed_task_outcome/embed_failure were only
ever called from app/agents/manager.py — every agent dispatched through
app/api/specialized_agents.py's background/sync run paths discarded its result
without writing anything to shared memory. These tests prove (a) the hook
itself writes the right records for the right outcomes, and (b) both real
dispatch call sites actually invoke it — a regression here means we're back
to the confirmed gap from MASTER_AGENT_v2.md §A.4.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.agent_result import AgentResult
from app.memory.hooks import record_agent_run_outcome

# ---------------------------------------------------------------------------
# record_agent_run_outcome — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_run_writes_task_outcome_only() -> None:
    result = AgentResult(
        summary="Fixed the null pointer in login",
        findings=["root cause: missing null check"],
        files_touched=["backend/app/auth.py"],
        verified=True,
        status="completed",
    )
    mock_db = AsyncMock()

    with (
        patch("app.memory.hooks.embed_task_outcome", new=AsyncMock()) as mock_outcome,
        patch("app.memory.hooks.embed_failure", new=AsyncMock()) as mock_failure,
    ):
        await record_agent_run_outcome(
            agent_name="debugger_agent",
            task_id="42",
            description="fix login bug",
            result=result,
            db=mock_db,
        )

    mock_outcome.assert_awaited_once()
    assert mock_outcome.await_args is not None
    call_kwargs = mock_outcome.await_args.kwargs
    assert call_kwargs["task_id"] == "42"
    assert call_kwargs["outcome"] == "completed"
    assert call_kwargs["summary"] == "Fixed the null pointer in login"
    assert call_kwargs["files_changed"] == ["backend/app/auth.py"]
    mock_failure.assert_not_awaited()


@pytest.mark.asyncio
async def test_blocked_run_writes_both_outcome_and_failure() -> None:
    result = AgentResult(
        summary="Could not reproduce the reported crash",
        findings=["tried 3 repro steps, none crashed"],
        files_touched=[],
        verified=False,
        status="blocked",
    )
    mock_db = AsyncMock()

    with (
        patch("app.memory.hooks.embed_task_outcome", new=AsyncMock()) as mock_outcome,
        patch("app.memory.hooks.embed_failure", new=AsyncMock()) as mock_failure,
    ):
        await record_agent_run_outcome(
            agent_name="debugger_agent",
            task_id="43",
            description="fix crash",
            result=result,
            db=mock_db,
            epic_id="epic-1",
        )

    mock_outcome.assert_awaited_once()
    assert mock_outcome.await_args is not None
    assert mock_outcome.await_args.kwargs["outcome"] == "blocked"
    assert mock_outcome.await_args.kwargs["epic_id"] == "epic-1"

    mock_failure.assert_awaited_once()
    assert mock_failure.await_args is not None
    fail_kwargs = mock_failure.await_args.kwargs
    assert fail_kwargs["task_id"] == "43"
    assert fail_kwargs["error_description"] == "Could not reproduce the reported crash"
    assert "tried 3 repro steps" in fail_kwargs["root_cause"]
    assert fail_kwargs["epic_id"] == "epic-1"


@pytest.mark.asyncio
async def test_memory_write_failure_does_not_raise() -> None:
    """A broken memory backend must never break the calling dispatch path."""
    result = AgentResult(summary="done", status="completed")
    mock_db = AsyncMock()

    with patch(
        "app.memory.hooks.embed_task_outcome",
        new=AsyncMock(side_effect=RuntimeError("db down")),
    ):
        await record_agent_run_outcome(
            agent_name="qa",
            task_id="1",
            description="task",
            result=result,
            db=mock_db,
        )
    # No exception propagated — test passing at all is the assertion.


# ---------------------------------------------------------------------------
# Wiring — both real dispatch call sites must actually call the hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_background_dispatch_calls_record_agent_run_outcome() -> None:
    from app.api.specialized_agents import _run_specialized_agent_bg

    fake_result = AgentResult(summary="ok", status="completed")

    mock_db = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.db.session.get_session_factory", return_value=mock_factory),
        patch("app.api.specialized_agents.append_log", new=AsyncMock()),
        patch("app.artifacts.store.save_artifact_async", new=AsyncMock()),
        patch("app.api.repo.get_active_repo_path", return_value="/repo"),
        patch(
            "app.api.specialized_agents._load_agent_fn",
            return_value=lambda **kwargs: fake_result,
        ),
        # Stage 4 Cluster O (2026-08-05) — a bare AsyncMock()'s child
        # attributes recursively default to AsyncMock too, so
        # mock_db.execute(...).scalar_one_or_none() silently returns an
        # unawaited coroutine instead of a real value/None. Patched
        # directly rather than trying to hand-configure that chain, and
        # given a real int so the wiring assertion below actually means
        # something (not just "didn't crash").
        patch("app.db.repository.get_task_repo_id", new=AsyncMock(return_value=42)),
        patch(
            "app.memory.hooks.record_agent_run_outcome", new=AsyncMock()
        ) as mock_hook,
    ):
        await _run_specialized_agent_bg(
            agent_name="debugger_agent",
            task_id=99,
            description="debug it",
            repo_path=None,
        )

    mock_hook.assert_awaited_once()
    assert mock_hook.await_args is not None
    kwargs = mock_hook.await_args.kwargs
    assert kwargs["agent_name"] == "debugger_agent"
    assert kwargs["task_id"] == "99"
    assert kwargs["description"] == "debug it"
    assert kwargs["result"] is fake_result
    assert kwargs["repo_id"] == 42


@pytest.mark.asyncio
async def test_run_sync_dispatch_calls_record_agent_run_outcome() -> None:
    from app.api.specialized_agents import RunAgentRequest, run_specialized_agent_sync

    fake_result = AgentResult(summary="ok", status="completed")
    mock_db = AsyncMock()

    with (
        patch("app.api.repo.get_active_repo_path", return_value="/repo"),
        patch(
            "app.api.specialized_agents._load_agent_fn",
            return_value=lambda **kwargs: fake_result,
        ),
        patch("app.artifacts.store.save_artifact_async", new=AsyncMock()),
        patch("app.api.specialized_agents.append_log", new=AsyncMock()),
        # Stage 4 Cluster O (2026-08-05) — same AsyncMock recursive-
        # coroutine pitfall as the background-dispatch test above; this
        # endpoint's new task lookup (get_task) hits it directly (no
        # intervening mocked function to absorb the garbage value), so it
        # must be patched here rather than left to the bare mock_db.
        # None simulates the legitimate "task not found" case.
        patch("app.db.repository.get_task", new=AsyncMock(return_value=None)),
        patch(
            "app.memory.hooks.record_agent_run_outcome", new=AsyncMock()
        ) as mock_hook,
    ):
        body = RunAgentRequest(task_id=7, description="do it", repo_path=None)
        await run_specialized_agent_sync(
            agent_name="debugger_agent", body=body, db=mock_db, _actor="tester"
        )

    mock_hook.assert_awaited_once()
    assert mock_hook.await_args is not None
    kwargs = mock_hook.await_args.kwargs
    assert kwargs["agent_name"] == "debugger_agent"
    assert kwargs["task_id"] == "7"
    assert kwargs["result"] is fake_result
    assert kwargs["repo_id"] is None
