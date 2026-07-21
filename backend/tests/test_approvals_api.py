"""Day 13 — the generic /api/approvals/* endpoints.

Drives a real pipeline run through the FastAPI TestClient (same mocked-LLM
pattern as Day 12's smoke test) into awaiting_approval, then exercises the
NEW generic endpoints (not the old /pipeline/approve) end-to-end, proving
they produce the same real resume behavior since approve/reject here just
call the same resume_planning_pipeline() the old endpoint already calls —
reused, not duplicated.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

_SUBMIT_TOOL_STUB_INPUT: dict[str, dict[str, Any]] = {
    "submit_subtasks": {
        "subtasks": [
            {
                "type": "backend",
                "title": "Add hello route",
                "description": "Add GET /hello handler.",
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
                id="tu_appr",
                name=submit_tool["name"],
                input=stub_input,
            )
        ],
        usage=SimpleNamespace(input_tokens=50, output_tokens=20),
    )


def _mock_anthropic_client() -> MagicMock:
    client = MagicMock()
    client.messages.create.side_effect = lambda *a, **kw: _submit_tool_use_response(
        kw.get("tools")
    )
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


def _run_pipeline_to_awaiting_approval(
    client: TestClient, mock_anthropic_cls: Any
) -> int:
    mock_anthropic_cls.return_value = _mock_anthropic_client()
    create_resp = client.post(
        "/api/tasks",
        json={"title": "Approvals API test task", "description": "Add GET /hello."},
    )
    assert create_resp.status_code == 201, create_resp.text
    task_id = create_resp.json()["id"]

    run_resp = client.post(f"/api/tasks/{task_id}/run", json={"mode": "full"})
    assert run_resp.status_code == 200, run_resp.text
    return int(task_id)


@patch("anthropic.Anthropic")
def test_pending_approval_row_created_and_listed(mock_anthropic_cls: Any) -> None:
    task_id: int | None = None
    try:
        with TestClient(app) as client:
            task_id = _run_pipeline_to_awaiting_approval(client, mock_anthropic_cls)

            thread_id = f"task-{task_id}"
            get_resp = client.get(f"/api/approvals/{thread_id}")
            assert get_resp.status_code == 200, get_resp.text
            body = get_resp.json()
            assert body["status"] == "pending"
            assert body["action"] == "plan_review"
            assert body["taskId"] == task_id
            assert body["details"]["subtasks_count"] >= 1

            list_resp = client.get("/api/approvals/pending")
            assert list_resp.status_code == 200
            thread_ids = {a["threadId"] for a in list_resp.json()["approvals"]}
            assert thread_id in thread_ids
    finally:
        if task_id is not None:
            _delete_task(task_id)


def test_get_approval_404_for_unknown_thread() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/approvals/task-nonexistent-999999")
        assert resp.status_code == 404


def test_approve_endpoint_404_for_unknown_thread() -> None:
    with TestClient(app) as client:
        resp = client.post("/api/approvals/task-nonexistent-999999/approve")
        assert resp.status_code == 404


@patch("app.api.agents.launch_manager")
@patch("anthropic.Anthropic")
def test_approve_via_generic_endpoint_resumes_pipeline_and_updates_status(
    mock_anthropic_cls: Any, mock_launch_manager: Any
) -> None:
    task_id: int | None = None
    try:
        with TestClient(app) as client:
            task_id = _run_pipeline_to_awaiting_approval(client, mock_anthropic_cls)
            thread_id = f"task-{task_id}"

            approve_resp = client.post(f"/api/approvals/{thread_id}/approve")
            assert approve_resp.status_code == 200, approve_resp.text

            task_data = client.get(f"/api/tasks/{task_id}").json()

        assert task_data["status"] == "ready_for_review"
        mock_launch_manager.assert_called_once()

        with TestClient(app) as client2:
            approval = client2.get(f"/api/approvals/{thread_id}").json()
        assert approval["status"] == "approved"
        assert approval["decidedBy"] == "user"
    finally:
        if task_id is not None:
            _delete_task(task_id)


@patch("anthropic.Anthropic")
def test_reject_via_generic_endpoint_marks_task_rejected(
    mock_anthropic_cls: Any,
) -> None:
    task_id: int | None = None
    try:
        with TestClient(app) as client:
            task_id = _run_pipeline_to_awaiting_approval(client, mock_anthropic_cls)
            thread_id = f"task-{task_id}"

            reject_resp = client.post(f"/api/approvals/{thread_id}/reject")
            assert reject_resp.status_code == 200, reject_resp.text

            task_data = client.get(f"/api/tasks/{task_id}").json()

        assert task_data["status"] == "rejected"

        with TestClient(app) as client2:
            approval = client2.get(f"/api/approvals/{thread_id}").json()
        assert approval["status"] == "rejected"
    finally:
        if task_id is not None:
            _delete_task(task_id)


@patch("anthropic.Anthropic")
def test_approve_twice_returns_409_second_time(mock_anthropic_cls: Any) -> None:
    task_id: int | None = None
    try:
        with TestClient(app) as client:
            task_id = _run_pipeline_to_awaiting_approval(client, mock_anthropic_cls)
            thread_id = f"task-{task_id}"

            with patch("app.api.agents.launch_manager"):
                first = client.post(f"/api/approvals/{thread_id}/approve")
                assert first.status_code == 200

            second = client.post(f"/api/approvals/{thread_id}/approve")
        assert second.status_code == 409
    finally:
        if task_id is not None:
            _delete_task(task_id)


def test_audit_log_has_the_approval_decision() -> None:
    """Success criterion: 'Audit log has the approval decision.'"""
    from app.fleet.audit_log import get_audit_log

    task_id: int | None = None
    try:
        with patch("anthropic.Anthropic") as mock_anthropic_cls, TestClient(
            app
        ) as client:
            task_id = _run_pipeline_to_awaiting_approval(client, mock_anthropic_cls)
            thread_id = f"task-{task_id}"

            with patch("app.api.agents.launch_manager"):
                resp = client.post(f"/api/approvals/{thread_id}/approve")
            assert resp.status_code == 200

        entries = get_audit_log().by_task(str(task_id))
        approval_entries = [e for e in entries if e.action_type == "plan_review"]
        assert len(approval_entries) >= 1
        assert approval_entries[-1].outcome == "approved"
    finally:
        if task_id is not None:
            _delete_task(task_id)
