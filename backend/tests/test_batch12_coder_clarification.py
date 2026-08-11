"""AUDIT_Q_BATCH12 §25/§29 gap-closure (2026-08-11) — extends request_
clarification's "clean stop, resume with a fresh run" pattern (already
proven for planner.py in tests/test_phase53_request_clarification.py) to
coder.py, the other flagship autonomous-authoring agent in the main
pipeline. Mirrors that file's own test shapes so the two integrations are
directly comparable.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.fleet.approval_gate import PendingApprovalRecord
from app.main import app

# ---------------------------------------------------------------------------
# coder.py contract + tool wiring
# ---------------------------------------------------------------------------


def test_coder_contract_declares_request_clarification() -> None:
    from app.agents.coder import AGENT_CONTRACT

    assert "request_clarification" in AGENT_CONTRACT["allowed_tools"]


class _ClarificationLLM:
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        tools = kwargs.get("tools") or []
        has_clarify = any(t.get("name") == "request_clarification" for t in tools)
        if has_clarify:
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="tu1",
                        name="request_clarification",
                        input={
                            "question": "Which pagination style?",
                            "context": "found cursor- and offset-based precedent",
                        },
                    )
                ],
                usage=SimpleNamespace(input_tokens=20, output_tokens=10),
            )
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="{}")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def test_coder_surfaces_clarification_via_existing_error_slot(tmp_path: Any) -> None:
    """External interface (return shape) deliberately unchanged — same
    parseable-prefix convention as run_planner, confirmed directly against
    the real run_coder(). files_changed must be [] — proves the short-
    circuit fires before the check-loop's false-success path."""
    from app.agents.coder import run_coder

    llm = _ClarificationLLM()
    with patch("app.agents.base_graph.load_role", return_value="# Coder\n"), patch(
        "anthropic.Anthropic"
    ) as mock_anthropic_cls, patch(
        "app.fleet.approval_gate.record_pending"
    ) as mock_record:
        mock_record.return_value = SimpleNamespace(id=1)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = llm
        mock_anthropic_cls.return_value = mock_client

        files_changed, error, tokens_in, tokens_out = run_coder(
            task_id=901,
            plan="## Implementation Steps\n1. Do the ambiguous thing.",
            worktree_path=str(tmp_path),
            repo_path=str(tmp_path),
        )

    assert files_changed == []
    assert error is not None
    assert error.startswith("[NEEDS_CLARIFICATION]")
    assert "Which pagination style?" in error
    mock_record.assert_called_once()
    assert mock_record.call_args.kwargs["thread_id"] == "clarify-901-coder"
    assert mock_record.call_args.kwargs["agent_name"] == "coder"


# ---------------------------------------------------------------------------
# api/approvals.py — clarification dispatch is agent-aware
#
# (blocked -> coding's VALID_TRANSITIONS entry has its own test in
# tests/test_status_transitions.py, the canonical home for state-machine
# assertions.)
# ---------------------------------------------------------------------------


def _clarification_row(agent_name: str) -> PendingApprovalRecord:
    return PendingApprovalRecord(
        id=1,
        thread_id=f"clarify-77-{agent_name}",
        task_id=77,
        agent_name=agent_name,
        action="clarification",
        details={"question": "q?", "context": "", "blocking": False},
        status="pending",
        created_at="2026-08-11T00:00:00",
        decided_at=None,
        decided_by=None,
    )


@pytest.mark.asyncio
async def test_dispatch_decision_routes_coder_clarification_to_coder_resume() -> None:
    from app.api.approvals import _dispatch_decision

    with patch(
        "app.api.agents.resume_coder_after_clarification", new=AsyncMock()
    ) as mock_coder_resume, patch(
        "app.api.agents.resume_planner_after_clarification", new=AsyncMock()
    ) as mock_planner_resume:
        await _dispatch_decision(
            _clarification_row("coder"), True, "use offset pagination"
        )

    mock_coder_resume.assert_called_once_with(77, "use offset pagination")
    mock_planner_resume.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_decision_routes_planner_clarification_to_planner_resume() -> (
    None
):
    from app.api.approvals import _dispatch_decision

    with patch(
        "app.api.agents.resume_coder_after_clarification", new=AsyncMock()
    ) as mock_coder_resume, patch(
        "app.api.agents.resume_planner_after_clarification", new=AsyncMock()
    ) as mock_planner_resume:
        await _dispatch_decision(_clarification_row("planner"), True, "use OAuth")

    mock_planner_resume.assert_called_once_with(77, "use OAuth")
    mock_coder_resume.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_decision_clarification_approved_with_no_answer_does_not_resume() -> (
    None
):
    from app.api.approvals import _dispatch_decision

    with patch(
        "app.api.agents.resume_coder_after_clarification", new=AsyncMock()
    ) as mock_coder_resume, patch(
        "app.api.agents.resume_planner_after_clarification", new=AsyncMock()
    ) as mock_planner_resume:
        await _dispatch_decision(_clarification_row("coder"), True, None)

    mock_coder_resume.assert_not_called()
    mock_planner_resume.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_decision_clarification_rejected_does_not_resume() -> None:
    from app.api.approvals import _dispatch_decision

    with patch(
        "app.api.agents.resume_coder_after_clarification", new=AsyncMock()
    ) as mock_coder_resume, patch(
        "app.api.agents.resume_planner_after_clarification", new=AsyncMock()
    ) as mock_planner_resume:
        await _dispatch_decision(
            _clarification_row("coder"), False, "use offset pagination"
        )

    mock_coder_resume.assert_not_called()
    mock_planner_resume.assert_not_called()


# ---------------------------------------------------------------------------
# api/agents.py::resume_coder_after_clarification — real DB integration
# ---------------------------------------------------------------------------


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _create_blocked_coder_task(local_path: str) -> tuple[int, int]:
    """A task as if launch_coder() had just paused it on request_
    clarification: status="blocked", a real plan already stored (set by an
    earlier launch_planner run), assigned to a real repo."""
    import asyncio

    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask, Repo
    from app.db.repository import create_task

    async def _run() -> tuple[int, int]:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                repo = Repo(
                    github_url="https://github.com/td-owner/td-coder-clarify-repo",
                    name="td-coder-clarify-repo",
                    local_path=local_path,
                    status="ready",
                )
                session.add(repo)
                await session.commit()
                await session.refresh(repo)

                task = await create_task(
                    session,
                    "coder clarification resume test",
                    "desc",
                    repo_id=repo.id,
                )
                await session.execute(
                    update(DevTask)
                    .where(DevTask.id == task.id)
                    .values(
                        status="blocked",
                        plan="## Implementation Steps\n1. Do the thing.",
                    )
                )
                await session.commit()
                return task.id, repo.id
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


def _get_task_status(task_id: int) -> str:
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask

    async def _run() -> str:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                task = await session.get(DevTask, task_id)
                assert task is not None
                return str(task.status)
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


def _cleanup(task_id: int, repo_id: int) -> None:
    import asyncio

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask, Repo

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(delete(DevTask).where(DevTask.id == task_id))
                await session.execute(delete(Repo).where(Repo.id == repo_id))
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _record_coder_clarification_pending(task_id: int) -> str:
    """Mirrors test_git_push_approval_dispatch.py's own
    _record_git_push_pending — ag.record_pending's sync wrapper is safe to
    call standalone (own internal asyncio.run(), own isolated call), the
    established pattern for seeding a PendingApproval row directly instead
    of driving a full mocked agent run just to produce one."""
    from app.fleet import approval_gate as ag

    thread_id = f"clarify-{task_id}-coder"
    ag.record_pending(
        thread_id,
        "clarification",
        {
            "question": "Which pagination style?",
            "context": "found cursor- and offset-based precedent",
            "blocking": False,
        },
        agent_name="coder",
        task_id=task_id,
    )
    return thread_id


def test_resume_coder_after_clarification_transitions_and_relaunches(
    tmp_path: Any,
) -> None:
    """dispatch_git_push_decision-style DB integration test (see that file's
    own docstring): resume_coder_after_clarification uses the shared,
    process-wide engine by design (meant to run inside FastAPI's
    BackgroundTasks on the app's own already-running event loop) — driven
    through a real TestClient request, matching the established Day 12/13/14
    pattern, not a bare asyncio.run() from sync test code."""
    task_id, repo_id = _create_blocked_coder_task(str(tmp_path))
    try:
        thread_id = _record_coder_clarification_pending(task_id)
        with patch("app.api.agents.launch_coder", new=AsyncMock()) as mock_launch_coder:
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/approvals/{thread_id}/approve",
                    json={"answer": "use offset pagination"},
                )
            assert resp.status_code == 200, resp.text

        mock_launch_coder.assert_called_once()
        call_args = mock_launch_coder.call_args
        assert call_args.args[0] == task_id
        assert "use offset pagination" in call_args.args[1]
        assert "Do the thing" in call_args.args[1]  # original plan preserved

        assert _get_task_status(task_id) == "coding"
    finally:
        _cleanup(task_id, repo_id)


def test_resume_coder_after_clarification_noop_for_wrong_status(
    tmp_path: Any,
) -> None:
    """A task not in "blocked" (e.g. already resumed by another path) must
    not be silently force-transitioned — mirrors resume_planner_after_
    clarification's identical guard."""
    task_id, repo_id = _create_blocked_coder_task(str(tmp_path))
    try:
        from sqlalchemy import update
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.db.models import DevTask

        async def _set_completed() -> None:
            engine = _new_isolated_db_engine()
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:  # type: ignore[arg-type]
                    await session.execute(
                        update(DevTask)
                        .where(DevTask.id == task_id)
                        .values(status="completed")
                    )
                    await session.commit()
            finally:
                await engine.dispose()  # type: ignore[attr-defined]

        import asyncio

        asyncio.run(_set_completed())

        thread_id = _record_coder_clarification_pending(task_id)
        with patch("app.api.agents.launch_coder", new=AsyncMock()) as mock_launch_coder:
            with TestClient(app) as client:
                resp = client.post(
                    f"/api/approvals/{thread_id}/approve",
                    json={"answer": "an answer"},
                )
            assert resp.status_code == 200, resp.text

        mock_launch_coder.assert_not_called()
        assert _get_task_status(task_id) == "completed"
    finally:
        _cleanup(task_id, repo_id)
