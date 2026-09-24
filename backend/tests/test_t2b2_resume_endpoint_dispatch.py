"""T2-B2 (2026-09-22, GRIDIRON_PARTIAL #212/#213) — real end-to-end proof
that POST /api/tasks/{id}/resume actually re-dispatches a resumable agent,
closing a real, confirmed dead end: before this, resume_task() only ever
called TaskStream.set_resume(), and nothing in the codebase ever called
TaskStream.pop_resume() to consume it — "Resume" cleared a flag and injected
a message nobody read.

Uses the real dev Postgres (create_task/create_agent_run_sync — the exact
same real functions production uses), a real TestClient against the real
app, and mocks only the agent's own run_* function (so this test proves the
real endpoint → registry → dispatch wiring without spending a real LLM
call — same rule this whole initiative applies to infrastructure tests).
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _new_task(client: TestClient) -> int:
    r = client.post(
        "/api/tasks", json={"title": "t2b2 resume dispatch", "description": "d"}
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _cleanup(task_id: int) -> None:
    import os

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def go() -> None:
        eng = create_async_engine(os.environ["DATABASE_URL"])
        async with eng.begin() as conn:
            await conn.execute(
                text("delete from dev_tasks where id = :i"), {"i": task_id}
            )
        await eng.dispose()

    asyncio.run(go())


def test_resume_dispatches_a_covered_agent_from_its_checkpoint(
    client: TestClient,
) -> None:
    from app.db.repository import create_agent_run_sync

    task_id = _new_task(client)
    try:
        trace_id = f"t2b2-endpoint-{task_id}"
        run_id = create_agent_run_sync(
            task_id, "bug_fix", "claude-haiku-4-5-20251001", trace_id=trace_id
        )
        assert run_id is not None
        assert client.post(f"/api/tasks/{task_id}/stop").status_code == 200

        # autospec=True — resume_registry.resolve_resume_call() decides
        # coverage via inspect.signature(fn); a plain MagicMock has no real
        # signature to introspect (it would report "no resume_trace_id
        # parameter" for every function equally), so the mock must actually
        # mirror the real one's signature.
        with patch("app.agents.bug_fix.run_bug_fix", autospec=True) as mock_run:
            mock_run.return_value = (
                None  # AgentResult shape not needed for this test's scope
            )

            r = client.post(
                f"/api/tasks/{task_id}/resume",
                json={"message": "please also handle the timeout case", "files": []},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["dispatched"] is True
            assert body["ok"] is True

            # TestClient runs BackgroundTasks synchronously after the response
            # (starlette's own documented behavior) — mock_run must have been
            # called by the time we get here.
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["task_id"] == task_id
            assert (
                call_kwargs["error_description"]
                == "please also handle the timeout case"
            )
            assert call_kwargs["resume_trace_id"] == trace_id
    finally:
        _cleanup(task_id)


def test_resume_falls_back_to_flag_only_for_an_uncovered_agent(
    client: TestClient,
) -> None:
    """security_reviewer has not been given resume_trace_id support in this
    batch — resume must still succeed (today's pre-existing behavior), just
    without a real dispatch, never a guessed/fabricated one."""
    from app.db.repository import create_agent_run_sync

    task_id = _new_task(client)
    try:
        trace_id = f"t2b2-endpoint-uncovered-{task_id}"
        run_id = create_agent_run_sync(
            task_id, "security_reviewer", "claude-haiku-4-5-20251001", trace_id=trace_id
        )
        assert run_id is not None
        assert client.post(f"/api/tasks/{task_id}/stop").status_code == 200

        r = client.post(
            f"/api/tasks/{task_id}/resume",
            json={"message": "continue please", "files": []},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dispatched"] is False
        assert body["ok"] is True
    finally:
        _cleanup(task_id)
