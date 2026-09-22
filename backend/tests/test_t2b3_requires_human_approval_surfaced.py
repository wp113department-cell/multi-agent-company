"""T2-B3 (2026-09-22, GRIDIRON_PARTIAL #130 "Confidence Evaluation feeds
control flow") — AgentResult.requires_human_approval was computed by every
real agent run and then silently dropped at app/api/specialized_agents.py's
two real persistence/response boundaries (_run_specialized_agent_bg's
artifact_payload, run_specialized_agent_sync's sync_artifact_payload AND its
RunAgentResponse) — the audit's own plan calls this out by name. These tests
prove the flag now survives both the /run background-dispatch artifact and
the /run-sync response, in both directions (True and False), using the same
mock-the-agent-function pattern already established in
tests/test_stage4_cluster_q_test_coverage_pct.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request

from app.agents.agent_result import AgentResult


def _fake_request() -> Request:
    return Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/api/specialized-agents/x/run-sync",
            "headers": [],
            "client": ("testclient", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


async def _run_bg_dispatch_and_capture_artifact(
    agent_name: str, fake_result: AgentResult
) -> dict[str, object]:
    from app.api.specialized_agents import _run_specialized_agent_bg

    mock_save = AsyncMock()
    with (
        patch("app.api.specialized_agents._load_agent_fn", return_value=lambda **kw: fake_result),
        patch("app.artifacts.store.save_artifact_async", new=mock_save),
        patch("app.api.specialized_agents.append_log", new=AsyncMock()),
        patch("app.api.repo.get_active_repo_path", return_value="/repo"),
        patch("app.db.repository.get_task_repo_id", new=AsyncMock(return_value=None)),
        patch("app.memory.hooks.record_agent_run_outcome", new=AsyncMock()),
    ):
        await _run_specialized_agent_bg(agent_name, 1, "d", "/repo")

    assert mock_save.await_args is not None
    return mock_save.await_args.args[2]


async def _run_sync_dispatch_and_capture(
    agent_name: str, fake_result: AgentResult
) -> tuple[dict[str, object], object]:
    from app.api.specialized_agents import RunAgentRequest, run_specialized_agent_sync

    mock_db = AsyncMock()
    mock_save = AsyncMock()
    with (
        patch("app.api.repo.get_active_repo_path", return_value="/repo"),
        patch(
            "app.api.specialized_agents._load_agent_fn",
            return_value=lambda **kwargs: fake_result,
        ),
        patch("app.artifacts.store.save_artifact_async", new=mock_save),
        patch("app.api.specialized_agents.append_log", new=AsyncMock()),
        patch("app.db.repository.get_task", new=AsyncMock(return_value=None)),
        patch("app.memory.hooks.record_agent_run_outcome", new=AsyncMock()),
    ):
        body = RunAgentRequest(task_id=1, description="d", repo_path=None)
        response = await run_specialized_agent_sync(
            request=_fake_request(),
            agent_name=agent_name,
            body=body,
            db=mock_db,
            _actor="tester",
        )

    assert mock_save.await_args is not None
    return mock_save.await_args.args[2], response


@pytest.mark.asyncio
async def test_bg_dispatch_persists_requires_human_approval_true() -> None:
    fake_result = AgentResult(
        summary="ok", status="completed", requires_human_approval=True
    )
    payload = await _run_bg_dispatch_and_capture_artifact("debugger_agent", fake_result)
    assert payload["requires_human_approval"] is True


@pytest.mark.asyncio
async def test_bg_dispatch_persists_requires_human_approval_false() -> None:
    fake_result = AgentResult(
        summary="ok", status="completed", requires_human_approval=False
    )
    payload = await _run_bg_dispatch_and_capture_artifact("debugger_agent", fake_result)
    assert payload["requires_human_approval"] is False


@pytest.mark.asyncio
async def test_run_sync_surfaces_requires_human_approval_true_in_response_and_artifact() -> (
    None
):
    fake_result = AgentResult(
        summary="ok", status="needs_approval", requires_human_approval=True
    )
    payload, response = await _run_sync_dispatch_and_capture("debugger_agent", fake_result)
    assert payload["requires_human_approval"] is True
    assert response.requires_human_approval is True


@pytest.mark.asyncio
async def test_run_sync_surfaces_requires_human_approval_false_in_response_and_artifact() -> (
    None
):
    fake_result = AgentResult(
        summary="ok", status="completed", requires_human_approval=False
    )
    payload, response = await _run_sync_dispatch_and_capture("debugger_agent", fake_result)
    assert payload["requires_human_approval"] is False
    assert response.requires_human_approval is False
