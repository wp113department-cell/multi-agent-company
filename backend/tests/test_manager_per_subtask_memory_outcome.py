"""#58 (2026-09-28, GRIDIRON_PARTIAL "Considers memory (past outcomes) in
selection") — plan14 follow-on #3 already built agent_historical_
performance end to end (memory_embeddings.agent_name, the background
rollup, FleetManager.select()'s memory_performance_factor), and
app.memory.hooks.record_agent_run_outcome already threads agent_name
through — but nothing called it from manager.py's own per-subtask
dev/QA/review dispatch loop, the highest-volume real path in this
pipeline. These tests prove _dispatch_one_subtask (via run_manager()) now
calls it with the real selected agent for that specific subtask, on both
a completed and a blocked outcome, and that a missing db session is a
harmless no-op (same "memory writes never break dispatch" convention as
record_agent_run_outcome's own docstring).
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.agents.qa import QAResult
from app.agents.reviewer import ReviewResult


def _patch_common(**overrides):
    from contextlib import ExitStack

    stack = ExitStack()
    mocks = {}
    mocks["backend_dev"] = stack.enter_context(
        patch("app.agents.backend_dev.run_backend_dev")
    )
    mocks["qa"] = stack.enter_context(patch("app.agents.qa.run_qa"))
    mocks["reviewer"] = stack.enter_context(patch("app.agents.reviewer.run_reviewer"))
    stack.enter_context(
        patch("app.repo_tools.worktree.get_diff", return_value="diff --git a/x b/x")
    )
    stack.enter_context(
        patch(
            "app.services.git_service.git_add",
            return_value={"ok": True, "stdout": "", "stderr": ""},
        )
    )
    stack.enter_context(
        patch(
            "app.services.git_service.git_commit",
            return_value={"ok": True, "stdout": "", "stderr": ""},
        )
    )
    mocks["record_outcome"] = stack.enter_context(
        patch("app.memory.hooks.record_agent_run_outcome")
    )
    stack.enter_context(patch("app.db.repository.get_task_repo_id", return_value=None))
    # publish_event does a real DB insert whenever `db` is not None — mocked
    # here (same convention as test_gap_closure_days0_18.py's own
    # TestManagerTraceIdAndCheckpointWiring) so a plain sentinel object can
    # stand in for `db` without needing a real AsyncSession/Postgres
    # connection; the memory-outcome write itself is exercised through the
    # mocked record_agent_run_outcome above, not a real embed.
    stack.enter_context(patch("app.event_bus.bus.publish_event"))
    return stack, mocks


_FAKE_DB = object()


def test_completed_subtask_records_a_real_per_agent_memory_outcome(
    tmp_path,
) -> None:
    from app.agents.manager import run_manager

    stack, mocks = _patch_common()
    with stack:
        mocks["backend_dev"].return_value = (["app/api/hello.py"], None, 0, 0)
        mocks["qa"].return_value = QAResult(
            status="passed",
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            typecheck_clean=True,
            lint_clean=True,
            summary="ok",
        )
        mocks["reviewer"].return_value = ReviewResult(
            verdict="approved", summary="looks good"
        )

        result = asyncio.run(
            run_manager(
                task_id=999_401,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "t", "description": "d"}
                ],
                worktree_path=str(tmp_path),
                plan="plan",
                repo_path=str(tmp_path),
                epic_id="epic-abc",
                db=_FAKE_DB,
            )
        )

    assert result["status"] == "completed"
    mocks["record_outcome"].assert_called_once()
    call_kwargs = mocks["record_outcome"].call_args.kwargs
    assert call_kwargs["agent_name"] == "backend_dev"
    assert call_kwargs["task_id"] == "999401"
    assert call_kwargs["epic_id"] == "epic-abc"
    assert call_kwargs["result"].status == "completed"


def test_blocked_subtask_records_a_blocked_outcome(tmp_path) -> None:
    from app.agents.manager import run_manager

    stack, mocks = _patch_common()
    with stack:
        mocks["backend_dev"].return_value = (["app/api/hello.py"], None, 0, 0)
        mocks["qa"].return_value = QAResult(
            status="failed",
            tests_run=1,
            tests_passed=0,
            tests_failed=1,
            typecheck_clean=True,
            lint_clean=True,
            summary="tests failed",
            errors=["assertion error"],
        )
        mocks["reviewer"].return_value = ReviewResult(verdict="approved", summary="n/a")

        asyncio.run(
            run_manager(
                task_id=999_402,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "t", "description": "d"}
                ],
                worktree_path=str(tmp_path),
                plan="plan",
                repo_path=str(tmp_path),
                db=_FAKE_DB,
            )
        )

    mocks["record_outcome"].assert_called()
    last_call_kwargs = mocks["record_outcome"].call_args.kwargs
    assert last_call_kwargs["result"].status == "blocked"


def test_no_db_session_skips_the_memory_write_without_raising(tmp_path) -> None:
    from app.agents.manager import run_manager

    stack, mocks = _patch_common()
    with stack:
        mocks["backend_dev"].return_value = (["app/api/hello.py"], None, 0, 0)
        mocks["qa"].return_value = QAResult(
            status="passed",
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            typecheck_clean=True,
            lint_clean=True,
            summary="ok",
        )
        mocks["reviewer"].return_value = ReviewResult(
            verdict="approved", summary="looks good"
        )

        result = asyncio.run(
            run_manager(
                task_id=999_403,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "t", "description": "d"}
                ],
                worktree_path=str(tmp_path),
                plan="plan",
                repo_path=str(tmp_path),
                db=None,
            )
        )

    assert result["status"] == "completed"
    mocks["record_outcome"].assert_not_called()


def test_memory_write_failure_never_breaks_subtask_dispatch(tmp_path) -> None:
    from app.agents.manager import run_manager

    stack, mocks = _patch_common()
    with stack:
        mocks["record_outcome"].side_effect = RuntimeError("boom")
        mocks["backend_dev"].return_value = (["app/api/hello.py"], None, 0, 0)
        mocks["qa"].return_value = QAResult(
            status="passed",
            tests_run=1,
            tests_passed=1,
            tests_failed=0,
            typecheck_clean=True,
            lint_clean=True,
            summary="ok",
        )
        mocks["reviewer"].return_value = ReviewResult(
            verdict="approved", summary="looks good"
        )

        result = asyncio.run(
            run_manager(
                task_id=999_404,
                subtasks=[
                    {"id": 1, "type": "backend", "title": "t", "description": "d"}
                ],
                worktree_path=str(tmp_path),
                plan="plan",
                repo_path=str(tmp_path),
                db=_FAKE_DB,
            )
        )

    assert result["status"] == "completed"
