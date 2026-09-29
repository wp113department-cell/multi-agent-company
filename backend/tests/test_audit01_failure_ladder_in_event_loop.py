"""Production audit 01 (2026-09-29) — failure ladder called from async code.

run_manager() is `async def` and calls failure_ladder.abort() /
request_human_review() directly. Both used a bare asyncio.run(), which raises
"cannot be called from a running event loop" — reproduced before the fix. The
manager's broad except swallowed it, so an epic halt or an exhausted subtask
never published TaskFailed / ReviewRequested. The existing manager tests
patched both functions with mocks, which is why this never surfaced.

These tests use the REAL functions and the real DB — no mocks of the ladder.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from app.fleet import failure_ladder as fl
from tests.test_failure_ladder import _delete_task, _get_status, _make_task


def test_abort_transitions_from_inside_a_running_event_loop() -> None:
    task_id = _make_task("audit01 abort in loop")
    try:

        async def _call() -> bool:
            return fl.abort(str(task_id), "halted in loop", trace_id="t-audit01")

        assert asyncio.run(_call()) is True
        assert _get_status(task_id) == "failed"
    finally:
        _delete_task(task_id)


def test_request_human_review_transitions_from_inside_a_running_event_loop() -> None:
    task_id = _make_task("audit01 human review in loop")
    try:

        async def _call() -> bool:
            return fl.request_human_review(
                str(task_id), "manager", "blocked in loop", trace_id="t-audit01"
            )

        assert asyncio.run(_call()) is True
        assert _get_status(task_id) == "blocked"
    finally:
        _delete_task(task_id)


def test_transition_false_publishes_event_without_touching_status() -> None:
    task_id = _make_task("audit01 transition false")
    published: list[Any] = []
    try:
        with patch("app.fleet.fleet_events.publish", side_effect=published.append):

            async def _call() -> tuple[bool, bool]:
                a = fl.abort(str(task_id), "r", trace_id="t", transition=False)
                h = fl.request_human_review(
                    str(task_id), "manager", "r", trace_id="t", transition=False
                )
                return a, h

            assert asyncio.run(_call()) == (False, False)
        # status untouched — launch_manager owns it
        assert _get_status(task_id) == "pending"
        types = [e.event_type.value for e in published]
        assert types == ["TaskFailed", "ReviewRequested"]
        assert all(e.task_id == str(task_id) for e in published)
    finally:
        _delete_task(task_id)


def test_run_manager_halt_really_publishes_task_failed() -> None:
    """End-to-end through the real run_manager() and the REAL abort()/
    request_human_review() — only the LLM-backed dev/QA agents and git are
    mocked. Before the fix neither event ever reached the bus."""
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.config import get_settings

    max_epic_failures = get_settings().manager_max_epic_failures
    subtasks = [
        {"id": i, "type": "backend", "title": f"s{i}", "description": "y"}
        for i in range(1, max_epic_failures + 1)
    ]
    published: list[Any] = []
    with patch("app.agents.backend_dev.run_backend_dev") as dev, patch(
        "app.agents.qa.run_qa"
    ) as qa, patch("app.services.git_service.git_add") as ga, patch(
        "app.services.git_service.git_commit"
    ) as gc, patch(
        "app.fleet.fleet_events.publish", side_effect=published.append
    ):
        dev.return_value = (["app/x.py"], None, 0, 0)
        ga.return_value = gc.return_value = {"ok": True, "stdout": "", "stderr": ""}
        qa.return_value = QAResult(
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
                task_id=999_301,
                subtasks=subtasks,
                worktree_path="/tmp/does-not-need-to-exist",
                plan="plan",
                repo_path="/home/pc-117/Documents/CRR2906",
            )
        )

    assert result["status"] == "halted"
    types = [e.event_type.value for e in published]
    assert "TaskFailed" in types
    assert "ReviewRequested" in types
    failed = [e for e in published if e.event_type.value == "TaskFailed"]
    assert failed[0].task_id == "999301"
