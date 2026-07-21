"""Day 12 Part 1 — end-to-end pipeline smoke test.

Verifies wiring that had ZERO prior test coverage anywhere in this codebase
(confirmed by grep before writing this file): the HTTP-level chain
POST /tasks -> POST /{id}/run -> pipeline pauses at human_review ->
POST /{id}/pipeline/approve -> resume_pipeline -> launch_manager scheduled.

Scope decision (see docs/DAY12_PLAN.md): run_backend_dev/run_qa/run_reviewer
already have their own dedicated test coverage elsewhere (test_session2_migration.py,
test_dispatcher.py, tests/pending/test_specialist_agents.py) — re-simulating
their full LLM tool-calling personas through a real git worktree here would
re-test already-covered internals, not the wiring gap this file exists to close.
So: the HTTP-level pipeline test uses a real dev-agent-free path (pm/architect/
decomposer, all read-only tool-callers), and run_manager()'s own orchestration
(subtask iteration, retry loop, status aggregation) is tested directly with
run_backend_dev/run_qa/run_reviewer mocked at their home modules — the same
"patch the home module, not the local-import call site" lesson already
documented in test_prompt_registry.py/test_versioned_memory.py.

No ANTHROPIC_API_KEY is configured in this environment, so all LLM calls are
mocked with a generic "return a tool_use block for whatever submit_* tool is
in this call's tool list" side_effect — this works uniformly across
pm/architect/decomposer's main call_llm turn AND their planner_node/
reflection_node calls, because those two nodes tolerate any malformed/
non-JSON response by falling back to safe defaults (verified by reading
base_graph.py's planner_node/reflection_node — both wrap their JSON parsing
in try/except with pre-set defaults).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


_SUBMIT_TOOL_STUB_INPUT: dict[str, dict[str, Any]] = {
    # Most submit_* handlers (pm/architect) ignore their input entirely —
    # {"smoke_test_stub": True} satisfies "non-empty result" for those. But
    # decomposer_node itself validates result["subtasks"] is a real non-empty
    # list before letting the pipeline proceed, so that one needs real shape.
    "submit_subtasks": {
        "subtasks": [
            {"type": "backend", "title": "Add hello route", "description": "Add GET /hello handler."},
        ]
    },
}


def _submit_tool_use_response(tools: list[dict[str, Any]] | None) -> Any:
    """Return a tool_use block for whichever submit_* tool is in this call's
    tool list. planner_node/reflection_node calls pass no matching tool (they
    call the LLM with no `tools` kwarg or an unrelated one) and gracefully
    degrade on the resulting non-JSON text; the main call_llm turn is the only
    one that actually consumes this as an action."""
    submit_tool = None
    for t in tools or []:
        if isinstance(t, dict) and str(t.get("name", "")).startswith("submit_"):
            submit_tool = t
            break

    if submit_tool is None:
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="{}")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )

    stub_input = _SUBMIT_TOOL_STUB_INPUT.get(submit_tool["name"], {"smoke_test_stub": True})
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use", id="tu_smoke", name=submit_tool["name"],
                input=stub_input,
            )
        ],
        usage=SimpleNamespace(input_tokens=50, output_tokens=20),
    )


def _mock_anthropic_client() -> MagicMock:
    client = MagicMock()

    def _create(*args: Any, **kwargs: Any) -> Any:
        return _submit_tool_use_response(kwargs.get("tools"))

    client.messages.create.side_effect = _create
    return client


def _delete_task(task_id: int) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.db.models import DevTask, PendingApproval

    async def _run() -> None:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                # pending_approvals has no FK/cascade to dev_tasks (loosely
                # coupled index table, Day 13) — clean it up explicitly too.
                await session.execute(delete(PendingApproval).where(PendingApproval.task_id == task_id))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


@patch("anthropic.Anthropic")
def test_pipeline_reaches_awaiting_approval_via_http(mock_anthropic_cls: Any) -> None:
    mock_anthropic_cls.return_value = _mock_anthropic_client()

    task_id: int | None = None
    try:
        with TestClient(app) as client:
            create_resp = client.post(
                "/api/tasks",
                json={
                    "title": "Add hello world endpoint",
                    "description": "Add GET /hello that returns {message: 'hello'}",
                },
            )
            assert create_resp.status_code == 201, create_resp.text
            task_id = create_resp.json()["id"]

            run_resp = client.post(f"/api/tasks/{task_id}/run", json={"mode": "full"})
            assert run_resp.status_code == 200, run_resp.text

            get_resp = client.get(f"/api/tasks/{task_id}")
            assert get_resp.status_code == 200, get_resp.text
            task_data = get_resp.json()

        # pm -> architect -> decomposer all completed and the pipeline is
        # correctly paused waiting for a human, not blocked on a real bug.
        assert task_data["status"] in ("planning", "ready_for_review"), (
            f"Unexpected task status after pipeline run: {task_data}"
        )

        subtasks_resp_status = None
        with TestClient(app) as client:
            subtasks_resp = client.get(f"/api/tasks/{task_id}/subtasks")
            subtasks_resp_status = subtasks_resp.status_code
            if subtasks_resp_status == 200:
                subtasks_data = subtasks_resp.json()

        assert subtasks_resp_status == 200, "subtasks endpoint should be reachable after pipeline run"
        assert len(subtasks_data.get("subtasks", [])) >= 1, (
            f"Decomposer produced no subtasks: {subtasks_data}"
        )
    finally:
        if task_id is not None:
            _delete_task(task_id)


@patch("app.api.agents.launch_manager")
@patch("anthropic.Anthropic")
def test_approve_resumes_pipeline_and_schedules_launch_manager(
    mock_anthropic_cls: Any, mock_launch_manager: Any
) -> None:
    mock_anthropic_cls.return_value = _mock_anthropic_client()
    # launch_manager is an `async def` — patch() auto-detects this and makes
    # mock_launch_manager an AsyncMock, so calling it already returns a real
    # awaitable for asyncio.create_task(launch_manager(...)) to schedule.

    task_id: int | None = None
    try:
        with TestClient(app) as client:
            create_resp = client.post(
                "/api/tasks",
                json={"title": "Add goodbye endpoint", "description": "Add GET /goodbye."},
            )
            assert create_resp.status_code == 201, create_resp.text
            task_id = create_resp.json()["id"]

            run_resp = client.post(f"/api/tasks/{task_id}/run", json={"mode": "full"})
            assert run_resp.status_code == 200, run_resp.text

            approve_resp = client.post(f"/api/tasks/{task_id}/pipeline/approve")
            assert approve_resp.status_code == 200, approve_resp.text

        mock_launch_manager.assert_called_once()
        call_args = mock_launch_manager.call_args
        assert call_args.args[0] == task_id or call_args.kwargs.get("task_id") == task_id
    finally:
        if task_id is not None:
            _delete_task(task_id)


def test_run_manager_orchestrates_one_subtask_to_completion() -> None:
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.agents.reviewer import ReviewResult

    with patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev, patch(
        "app.agents.qa.run_qa"
    ) as mock_qa, patch("app.agents.reviewer.run_reviewer") as mock_reviewer, patch(
        "app.repo_tools.worktree.get_diff", return_value="diff --git a/x b/x"
    ):
        mock_backend_dev.return_value = (["app/api/hello.py"], None)
        mock_qa.return_value = QAResult(
            status="passed", tests_run=3, tests_passed=3, tests_failed=0,
            typecheck_clean=True, lint_clean=True, summary="all green",
        )
        mock_reviewer.return_value = ReviewResult(verdict="approved", summary="looks good")

        result = asyncio.run(
            run_manager(
                task_id=999_001,
                subtasks=[{"id": 1, "type": "backend", "title": "Add hello route", "description": "..."}],
                worktree_path="/tmp/does-not-need-to-exist-for-mocked-agents",
                plan="Add GET /hello",
                repo_path="/home/pc-117/Documents/CRR2906",
            )
        )

    assert result["status"] == "completed"
    assert result["blocked_count"] == 0
    assert len(result["results"]) == 1
    assert result["results"][0]["status"] == "completed"
    mock_backend_dev.assert_called_once()
    mock_qa.assert_called_once()
    mock_reviewer.assert_called_once()


def test_run_manager_retries_after_qa_failure_then_succeeds() -> None:
    from app.agents.manager import run_manager
    from app.agents.qa import QAResult
    from app.agents.reviewer import ReviewResult

    qa_responses = iter([
        QAResult(status="failed", tests_run=3, tests_passed=1, tests_failed=2,
                  typecheck_clean=True, lint_clean=True, errors=["test_x failed"], summary="2 failing"),
        QAResult(status="passed", tests_run=3, tests_passed=3, tests_failed=0,
                  typecheck_clean=True, lint_clean=True, summary="all green"),
    ])

    with patch("app.agents.backend_dev.run_backend_dev") as mock_backend_dev, patch(
        "app.agents.qa.run_qa"
    ) as mock_qa, patch("app.agents.reviewer.run_reviewer") as mock_reviewer, patch(
        "app.repo_tools.worktree.get_diff", return_value=""
    ):
        mock_backend_dev.return_value = (["app/api/hello.py"], None)
        mock_qa.side_effect = lambda *a, **kw: next(qa_responses)
        mock_reviewer.return_value = ReviewResult(verdict="approved", summary="looks good")

        result = asyncio.run(
            run_manager(
                task_id=999_002,
                subtasks=[{"id": 1, "type": "backend", "title": "Add hello route", "description": "..."}],
                worktree_path="/tmp/does-not-need-to-exist-for-mocked-agents",
                plan="Add GET /hello",
                repo_path="/home/pc-117/Documents/CRR2906",
            )
        )

    assert result["status"] == "completed"
    assert result["results"][0]["status"] == "completed"
    assert mock_qa.call_count == 2  # first failed, retried, second passed
    assert mock_backend_dev.call_count == 2  # dev agent re-runs each retry attempt
