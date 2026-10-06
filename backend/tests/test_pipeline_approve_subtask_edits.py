"""#227 (2026-09-28) — real HTTP-level test of POST /{id}/pipeline/approve
with subtask_edits, mirroring test_day12_smoke_test.py's own established
real-Postgres, real-TestClient, mocked-Anthropic-only convention (its
test_approve_resumes_pipeline_and_schedules_launch_manager is the direct
sibling this file extends).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

_SUBMIT_TOOL_STUB_INPUT: dict[str, dict[str, Any]] = {
    # Valid minimal answers: submit_brief / submit_architect_plan are strict
    # (STRICT_SUBMIT_TOOLS, 2026-10-06), so a placeholder is rejected.
    "submit_brief": {
        "goals": ["Add the endpoint"],
        "constraints": [],
        "acceptance_criteria": ["Endpoint returns 200"],
        "out_of_scope": [],
    },
    "submit_architect_plan": {
        "technical_approach": "Add a route in the existing router.",
        "impacted_files": [{"path": "backend/app/main.py", "reason": "register route"}],
        "risks": [],
        "risk_level": "low",
    },
    "submit_subtasks": {
        "subtasks": [
            {
                "type": "backend",
                "title": "Add hello route",
                "description": "Add GET /hello handler.",
            },
            {
                "type": "backend",
                "title": "Add tests",
                "description": "Add tests for /hello.",
                "depends_on": [0],
            },
        ]
    },
}


def _submit_tool_use_response(tools: list[dict[str, Any]] | None) -> Any:
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

    stub_input = _SUBMIT_TOOL_STUB_INPUT.get(
        submit_tool["name"], {"smoke_test_stub": True}
    )
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                id="tu_smoke",
                name=submit_tool["name"],
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
                await session.execute(
                    delete(PendingApproval).where(PendingApproval.task_id == task_id)
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


@patch("app.api.agents.launch_manager")
@patch("anthropic.Anthropic")
def test_approve_with_a_subtask_edit_reaches_launch_manager_edited(
    mock_anthropic_cls: Any, mock_launch_manager: Any
) -> None:
    mock_anthropic_cls.return_value = _mock_anthropic_client()

    task_id: int | None = None
    try:
        with TestClient(app) as client:
            create_resp = client.post(
                "/api/tasks",
                json={
                    "title": "Add hello world endpoint",
                    "description": "Add GET /hello.",
                },
            )
            assert create_resp.status_code == 201, create_resp.text
            task_id = create_resp.json()["id"]

            run_resp = client.post(f"/api/tasks/{task_id}/run", json={"mode": "full"})
            assert run_resp.status_code == 200, run_resp.text

            approve_resp = client.post(
                f"/api/tasks/{task_id}/pipeline/approve",
                json={
                    "subtask_edits": [
                        {
                            "index": 0,
                            "action": "edit",
                            "title": "Add hello route (human-edited)",
                        }
                    ]
                },
            )
            assert approve_resp.status_code == 200, approve_resp.text

        mock_launch_manager.assert_called_once()
        call_args = mock_launch_manager.call_args
        subtasks_arg = (
            call_args.args[1]
            if len(call_args.args) > 1
            else call_args.kwargs.get("subtasks")
        )
        assert subtasks_arg[0]["title"] == "Add hello route (human-edited)"
    finally:
        if task_id is not None:
            _delete_task(task_id)


@patch("app.api.agents.launch_manager")
@patch("anthropic.Anthropic")
def test_approve_with_a_rejected_leaf_subtask_removes_it(
    mock_anthropic_cls: Any, mock_launch_manager: Any
) -> None:
    mock_anthropic_cls.return_value = _mock_anthropic_client()

    task_id: int | None = None
    try:
        with TestClient(app) as client:
            create_resp = client.post(
                "/api/tasks",
                json={"title": "Add hello world endpoint", "description": "d"},
            )
            assert create_resp.status_code == 201, create_resp.text
            task_id = create_resp.json()["id"]

            run_resp = client.post(f"/api/tasks/{task_id}/run", json={"mode": "full"})
            assert run_resp.status_code == 200, run_resp.text

            approve_resp = client.post(
                f"/api/tasks/{task_id}/pipeline/approve",
                json={"subtask_edits": [{"index": 1, "action": "reject"}]},
            )
            assert approve_resp.status_code == 200, approve_resp.text

        mock_launch_manager.assert_called_once()
        call_args = mock_launch_manager.call_args
        subtasks_arg = (
            call_args.args[1]
            if len(call_args.args) > 1
            else call_args.kwargs.get("subtasks")
        )
        assert len(subtasks_arg) == 1
        assert subtasks_arg[0]["title"] == "Add hello route"
    finally:
        if task_id is not None:
            _delete_task(task_id)


@patch("anthropic.Anthropic")
def test_approve_rejecting_a_step_its_sibling_depends_on_returns_400(
    mock_anthropic_cls: Any,
) -> None:
    mock_anthropic_cls.return_value = _mock_anthropic_client()

    task_id: int | None = None
    try:
        with TestClient(app) as client:
            create_resp = client.post(
                "/api/tasks",
                json={"title": "Add hello world endpoint", "description": "d"},
            )
            assert create_resp.status_code == 201, create_resp.text
            task_id = create_resp.json()["id"]

            run_resp = client.post(f"/api/tasks/{task_id}/run", json={"mode": "full"})
            assert run_resp.status_code == 200, run_resp.text

            # subtask 1 ("Add tests") depends_on [0] ("Add hello route") —
            # rejecting index 0 alone must be refused, not silently corrupt
            # the remaining plan's dependency graph.
            approve_resp = client.post(
                f"/api/tasks/{task_id}/pipeline/approve",
                json={"subtask_edits": [{"index": 0, "action": "reject"}]},
            )
            assert approve_resp.status_code == 400, approve_resp.text
            assert "still depends on it" in approve_resp.text

            # Plan must be untouched — still approvable normally afterward.
            get_resp = client.get(f"/api/tasks/{task_id}")
            assert get_resp.json()["status"] == "planning"
    finally:
        if task_id is not None:
            _delete_task(task_id)


@patch("anthropic.Anthropic")
def test_plain_approve_with_no_body_still_works_unchanged(
    mock_anthropic_cls: Any,
) -> None:
    """Backward compatibility: every existing caller that sends no body
    (or an empty one) at all must see zero behavior change."""
    mock_anthropic_cls.return_value = _mock_anthropic_client()

    task_id: int | None = None
    try:
        with TestClient(app) as client, patch(
            "app.api.agents.launch_manager"
        ) as mock_launch_manager:
            create_resp = client.post(
                "/api/tasks",
                json={"title": "Add hello world endpoint", "description": "d"},
            )
            assert create_resp.status_code == 201, create_resp.text
            task_id = create_resp.json()["id"]

            run_resp = client.post(f"/api/tasks/{task_id}/run", json={"mode": "full"})
            assert run_resp.status_code == 200, run_resp.text

            approve_resp = client.post(f"/api/tasks/{task_id}/pipeline/approve")
            assert approve_resp.status_code == 200, approve_resp.text

        mock_launch_manager.assert_called_once()
    finally:
        if task_id is not None:
            _delete_task(task_id)
