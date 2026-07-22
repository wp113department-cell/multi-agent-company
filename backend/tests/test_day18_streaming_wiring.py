"""Day 18 — Real-Time Streaming to Frontend (Pipeline Events).

The real gap this day closes: app/services/activity_stream.py (the fully
built SSE mechanism, already correctly used by chat) and
app/api/activity.py's GET /api/tasks/{id}/stream (the exact endpoint the
plan's own pseudocode asks for) already existed — but task_id was never
threaded into run_agent_graph() from any of the 8 real pipeline/dev-agent
runners, confirmed by grep before writing this file. These tests verify
each runner now passes task_id, and that the two new event types
(push_agent_switch, push_approval_required — one documented but never
implemented, one entirely new) fire at the real transition points.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

_SUBMITTED_STATE = {
    "messages": [],
    "verification": {},
    "result": {
        "technical_approach": "x",
        "impacted_files": [],
        "risks": [],
        "risk_level": "low",
    },
    "turns": 1,
    "submitted": True,
    "requires_human_approval": False,
    "tokens_in": 10,
    "tokens_out": 10,
}


class TestPipelineNodesThreadTaskId:
    """pm_node / architect_node / decomposer_node take task_id from
    PipelineState (already available there) and must forward it into
    run_agent_graph() so activity_stream's push_* calls (gated on `if
    task_id:`) actually fire for a real task."""

    def test_pm_node_passes_task_id(self) -> None:
        from app.agents.pm import pm_node

        state = {
            "task_id": 42,
            "task_title": "t",
            "task_description": "d",
            "repo_path": "/tmp",
        }
        with patch(
            "app.agents.pm.run_agent_graph", return_value=_SUBMITTED_STATE
        ) as mock_graph:
            pm_node(state)  # type: ignore[arg-type]
        assert mock_graph.call_args.kwargs["task_id"] == "42"

    def test_architect_node_passes_task_id(self) -> None:
        from app.agents.architect import architect_node

        state = {
            "task_id": 43,
            "task_title": "t",
            "pm_brief": {},
            "repo_path": "/tmp",
        }
        with patch(
            "app.agents.architect.run_agent_graph", return_value=_SUBMITTED_STATE
        ) as mock_graph:
            architect_node(state)  # type: ignore[arg-type]
        assert mock_graph.call_args.kwargs["task_id"] == "43"

    def test_decomposer_node_passes_task_id(self) -> None:
        from app.agents.decomposer import decomposer_node

        state = {
            "task_id": 44,
            "task_title": "t",
            "pm_brief": {},
            "architect_plan": {},
            "repo_path": "/tmp",
        }
        submitted_with_subtasks = {
            **_SUBMITTED_STATE,
            "result": {
                "subtasks": [{"type": "backend", "title": "x", "description": "y"}]
            },
        }
        with patch(
            "app.agents.decomposer.run_agent_graph",
            return_value=submitted_with_subtasks,
        ) as mock_graph:
            decomposer_node(state)  # type: ignore[arg-type]
        assert mock_graph.call_args.kwargs["task_id"] == "44"


class TestDevAgentsThreadTaskId:
    """run_backend_dev / run_frontend_dev / run_coder / run_qa / run_reviewer
    already take task_id: int as their own parameter — must forward it."""

    def test_run_backend_dev_passes_task_id(self) -> None:
        from app.agents.backend_dev import run_backend_dev

        with patch(
            "app.agents.backend_dev.run_agent_graph", return_value=_SUBMITTED_STATE
        ) as mock_graph, patch(
            "app.agents.backend_dev.make_coder_handlers",
            return_value={"_patch_result": {"files_changed": ["a.py"]}},
        ), patch(
            "app.agents.backend_dev._run_backend_checks", return_value=None
        ):
            run_backend_dev(task_id=51, subtask_id=1, plan="p", worktree_path="/tmp/wt")
        assert mock_graph.call_args.kwargs["task_id"] == "51"

    def test_run_frontend_dev_passes_task_id(self) -> None:
        from app.agents.frontend_dev import run_frontend_dev

        with patch(
            "app.agents.frontend_dev.run_agent_graph", return_value=_SUBMITTED_STATE
        ) as mock_graph, patch(
            "app.agents.frontend_dev.make_coder_handlers",
            return_value={"_patch_result": {"files_changed": ["a.tsx"]}},
        ), patch(
            "app.agents.frontend_dev._run_frontend_checks", return_value=None
        ):
            run_frontend_dev(
                task_id=52, subtask_id=1, plan="p", worktree_path="/tmp/wt"
            )
        assert mock_graph.call_args.kwargs["task_id"] == "52"

    def test_run_coder_passes_task_id(self) -> None:
        from app.agents.coder import run_coder

        with patch(
            "app.agents.coder.run_agent_graph", return_value=_SUBMITTED_STATE
        ) as mock_graph, patch(
            "app.agents.coder.make_coder_handlers",
            return_value={"_patch_result": {"files_changed": ["a.py"]}},
        ), patch(
            "app.agents.coder._run_checks", return_value=None
        ):
            run_coder(task_id=53, plan="p", worktree_path="/tmp/wt")
        assert mock_graph.call_args.kwargs["task_id"] == "53"

    def test_run_qa_passes_task_id(self) -> None:
        from app.agents.qa import run_qa

        qa_state = {**_SUBMITTED_STATE, "result": {"status": "passed", "summary": "ok"}}
        with patch(
            "app.agents.qa.run_agent_graph", return_value=qa_state
        ) as mock_graph, patch("app.agents.qa.make_qa_handlers", return_value={}):
            run_qa(
                task_id=54,
                subtask_id=1,
                files_changed=["a.py"],
                worktree_path="/tmp/wt",
            )
        assert mock_graph.call_args.kwargs["task_id"] == "54"

    def test_run_reviewer_passes_task_id(self) -> None:
        from app.agents.reviewer import run_reviewer

        review_state = {**_SUBMITTED_STATE, "result": {"findings": []}}
        with patch(
            "app.agents.reviewer.run_agent_graph", return_value=review_state
        ) as mock_graph, patch(
            "app.agents.reviewer.make_reviewer_handlers", return_value={}
        ):
            run_reviewer(task_id=55, subtask_id=1, diff="d", plan="p")
        assert mock_graph.call_args.kwargs["task_id"] == "55"


class TestAgentSwitchWiredAtRealTransitions:
    def test_pm_node_pushes_agent_switch(self) -> None:
        from app.agents.pm import pm_node

        state = {
            "task_id": 60,
            "task_title": "t",
            "task_description": "d",
            "repo_path": "/tmp",
        }
        with patch(
            "app.agents.pm.run_agent_graph", return_value=_SUBMITTED_STATE
        ), patch("app.services.activity_stream.push_agent_switch") as mock_switch:
            pm_node(state)  # type: ignore[arg-type]
        mock_switch.assert_called_once_with("60", "pm", "planning")

    def test_manager_pushes_agent_switch_for_each_dispatch(self) -> None:
        """run_manager()'s subtask loop must announce backend_dev/
        frontend_dev/qa/reviewer transitions — the real dev->qa->review
        pipeline, not just the planning pipeline."""
        import asyncio

        from app.agents.manager import run_manager

        subtasks = [{"id": 1, "type": "backend", "title": "t", "description": "d"}]

        async def _fake_backend_dev(**kwargs):
            return ["a.py"], None

        async def _fake_qa(**kwargs):
            return MagicMock(status="passed", summary="ok", errors=[])

        async def _fake_reviewer(**kwargs):
            result = MagicMock()
            result.summary = "looks good"
            result.findings = []
            result.has_blocking = False
            return result

        with patch(
            "app.agents.backend_dev.run_backend_dev",
            side_effect=lambda **kw: (["a.py"], None),
        ), patch(
            "app.agents.qa.run_qa",
            side_effect=lambda **kw: MagicMock(
                status="passed", summary="ok", errors=[]
            ),
        ), patch(
            "app.agents.reviewer.run_reviewer",
            side_effect=lambda **kw: MagicMock(
                summary="ok", findings=[], has_blocking=False
            ),
        ), patch(
            "app.repo_tools.worktree.get_diff", return_value=""
        ), patch(
            "app.event_bus.bus.publish_event"
        ), patch(
            "app.services.git_service.git_add", return_value={"ok": True, "stderr": ""}
        ), patch(
            "app.services.git_service.git_commit",
            return_value={"ok": True, "stderr": ""},
        ), patch(
            "app.services.activity_stream.push_agent_switch"
        ) as mock_switch:
            asyncio.run(
                run_manager(
                    task_id=61,
                    subtasks=subtasks,
                    worktree_path="/tmp/wt",
                    plan="p",
                )
            )

        agents_announced = [c.args[1] for c in mock_switch.call_args_list]
        assert "backend_dev" in agents_announced
        assert "qa" in agents_announced
        assert "reviewer" in agents_announced
        assert all(c.args[0] == "61" for c in mock_switch.call_args_list)


def _new_isolated_db_engine() -> object:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import get_settings

    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


def _create_task(title: str) -> int:
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.repository import create_task

    async def _run() -> int:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:  # type: ignore[arg-type]
                task = await create_task(db, title, "desc")
                return task.id
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    return asyncio.run(_run())


def _cleanup_task(task_id: int) -> None:
    import asyncio

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import DevTask, PendingApproval

    async def _run() -> None:
        engine = _new_isolated_db_engine()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:  # type: ignore[arg-type]
                await db.execute(
                    delete(PendingApproval).where(PendingApproval.task_id == task_id)
                )
                await db.execute(delete(DevTask).where(DevTask.id == task_id))
                await db.commit()
        finally:
            await engine.dispose()  # type: ignore[attr-defined]

    asyncio.run(_run())


class TestApprovalRequiredWiredAtRealRecordingPoints:
    def test_plan_review_pushes_approval_required(self) -> None:
        """launch_planning_pipeline() uses the shared, process-wide
        get_session_factory() singleton by design (runs inside FastAPI's
        BackgroundTasks) — per the documented asyncio shared-engine hazard,
        driven through a real TestClient (one continuous event loop), not a
        bare asyncio.run() from sync test code."""
        from fastapi.testclient import TestClient

        from app.main import app
        from app.services.activity_stream import get_activity_registry

        task_id = _create_task("td day18 approval test")
        try:
            registry = get_activity_registry()
            registry.create(str(task_id))

            async def _fake_run_planning_pipeline(*a, **kw):
                return {
                    "stage": "done",
                    "pm_brief": {},
                    "architect_plan": {"risk_level": "low"},
                    "subtasks": [{"type": "backend", "title": "x", "description": "y"}],
                }

            # Day 15's bootstrap only runs against a genuinely blank repo —
            # not what this test is about, so skip it entirely.
            with patch(
                "app.pipeline.bootstrap.is_blank_repo", return_value=False
            ), patch(
                "app.pipeline.graph.run_planning_pipeline",
                side_effect=_fake_run_planning_pipeline,
            ):
                with TestClient(app) as client:
                    resp = client.post(
                        f"/api/tasks/{task_id}/run", json={"mode": "full"}
                    )
                assert resp.status_code == 200, resp.text

            stream = registry.get(str(task_id))
            assert stream is not None
            events = []
            while not stream._queue.empty():
                events.append(stream._queue.get_nowait())
            approval_events = [e for e in events if e["type"] == "approval_required"]
            assert (
                approval_events
            ), f"expected an approval_required event, got: {events}"
            assert approval_events[0]["action"] == "plan_review"

            registry.remove(str(task_id))
        finally:
            _cleanup_task(task_id)
