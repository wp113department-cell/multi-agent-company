"""Tests for MASTER_AGENT_v2.md Phase 5.6 (remaining) — manager.py's subtask
retry loop must catch SlotAcquisitionTimeout (Phase 5.6b, already real in
app/pipeline/concurrency.py) and route it through the exact same
retry/escalate path a real dev/QA/reviewer failure already uses, preserving
the loop's own documented "nothing raises past this function" invariant
instead of letting the new exception type propagate uncaught — confirmed
by reading _run_epic_manager_body/run_epic_manager in full before this fix:
neither had any try/except of their own, so an uncaught exception here
would have broken that invariant for the first time.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import patch

from app.agents.manager import run_manager
from app.agents.qa import QAResult
from app.pipeline.concurrency import SlotAcquisitionTimeout


@asynccontextmanager
async def _always_times_out() -> AsyncIterator[None]:
    raise SlotAcquisitionTimeout("agent_run", 0.01)
    yield  # pragma: no cover - unreachable, satisfies the generator shape


def test_agent_run_slot_timeout_during_dev_dispatch_is_handled_gracefully() -> None:
    """A slot timeout acquiring the dev-agent's run slot must not raise past
    run_manager — it must come back as a real 'blocked' subtask result,
    exactly like a real dev-agent failure would."""
    with patch("app.pipeline.concurrency.agent_run_slot", _always_times_out):
        result = asyncio.run(
            run_manager(
                task_id=999_301,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "x", "description": "y"}
                ],
                worktree_path="/tmp/does-not-need-to-exist",
                plan="plan",
                repo_path="/home/pc-117/Documents/CRR2906",
            )
        )

    # Must not have raised — reaching here at all is part of the proof.
    assert result["status"] == "blocked"
    assert result["results"][0]["status"] == "blocked"


def test_subtask_slot_timeout_before_loop_starts_is_handled_gracefully() -> None:
    """A timeout acquiring the per-epic subtask slot itself (before the
    dev/QA/reviewer retry loop even starts) must also come back as a real
    blocked result, not an uncaught exception, and must never call
    subtask_slot's __aexit__ (it was never successfully entered)."""

    class _TimeoutCM:
        async def __aenter__(self) -> None:
            raise SlotAcquisitionTimeout("subtask", 0.01)

        async def __aexit__(self, *exc: object) -> None:
            raise AssertionError(
                "must never be called — __aenter__ never actually acquired anything"
            )

    with patch("app.pipeline.concurrency.subtask_slot", return_value=_TimeoutCM()):
        result = asyncio.run(
            run_manager(
                task_id=999_302,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "x", "description": "y"}
                ],
                worktree_path="/tmp/does-not-need-to-exist",
                plan="plan",
                repo_path="/home/pc-117/Documents/CRR2906",
            )
        )

    assert result["status"] == "blocked"
    assert result["blocked_count"] == 1
    assert result["results"][0]["status"] == "blocked"


def test_agent_run_slot_timeout_during_qa_dispatch_is_handled_gracefully() -> None:
    """QA's own agent_run_slot() call site — a separate wiring point from
    the dev-dispatch one, confirmed independently rather than assumed to
    share behavior just because it looks similar."""
    with (
        patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev,
        patch("app.pipeline.concurrency.agent_run_slot", _always_times_out),
        patch("app.services.git_service.git_add") as mock_git_add,
        patch("app.services.git_service.git_commit") as mock_git_commit,
    ):
        mock_backend_dev.return_value = (["app/api/hello.py"], None, 0, 0)
        mock_git_add.return_value = {"ok": True, "stdout": "", "stderr": ""}
        mock_git_commit.return_value = {"ok": True, "stdout": "", "stderr": ""}

        result = asyncio.run(
            run_manager(
                task_id=999_303,
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


def test_agent_run_slot_timeout_during_reviewer_dispatch_is_handled_gracefully() -> (
    None
):
    with (
        patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev,
        patch("app.agents.qa.run_qa") as mock_qa,
        patch("app.pipeline.concurrency.agent_run_slot", _always_times_out),
        patch("app.repo_tools.worktree.get_diff", return_value=""),
        patch("app.services.git_service.git_add") as mock_git_add,
        patch("app.services.git_service.git_commit") as mock_git_commit,
    ):
        mock_backend_dev.return_value = (["app/api/hello.py"], None, 0, 0)
        mock_git_add.return_value = {"ok": True, "stdout": "", "stderr": ""}
        mock_git_commit.return_value = {"ok": True, "stdout": "", "stderr": ""}
        # QA itself doesn't hit the (mocked) agent_run_slot patch above since
        # it's imported+called inside manager.py's own try/except wrapping —
        # mock run_qa directly so only the reviewer's slot acquisition times out.
        mock_qa.return_value = QAResult(
            status="passed",
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            typecheck_clean=True,
            lint_clean=True,
            summary="ok",
        )

        result = asyncio.run(
            run_manager(
                task_id=999_304,
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
