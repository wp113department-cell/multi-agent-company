"""Verification batch B2, items #69 (stop execution), #70 (retry/restart) and the
Cancel/Resume semantics they interact with.

Defect proven by reading + reproduced here: the in-process abort flag set by Stop /
Cancel was only ever cleared by /resume. Restarting or re-running the task (or a
stray Stop on an idle task) left it set, so the NEXT run aborted at its first LLM
call ("stopped") and finished having done no work, until the server restarted.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.activity_stream import get_activity_registry


@pytest.fixture
def client():
    # context manager => ONE event loop for every request (the shared async DB
    # engine is bound to it; a bare TestClient spins up a loop per call)
    with TestClient(app) as c:
        yield c


def _set_status(tid: int, status: str) -> None:
    """Direct status write through a PRIVATE engine: touching the app's shared
    AsyncEngine singleton from a throwaway event loop is the documented
    "Event loop is closed" hazard."""
    import asyncio
    import os

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def go() -> None:
        eng = create_async_engine(os.environ["DATABASE_URL"])
        async with eng.begin() as conn:
            await conn.execute(
                text("update dev_tasks set status = :s where id = :i"),
                {"s": status, "i": tid},
            )
        await eng.dispose()

    asyncio.run(go())


def _new_task(client: TestClient, status: str = "blocked") -> int:
    r = client.post("/api/tasks", json={"title": "t", "description": "d"})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    _set_status(tid, status)
    return tid


def _flag(tid: int) -> bool:
    return get_activity_registry().should_abort(str(tid))


def test_stop_sets_the_flag_and_the_next_llm_call_honours_it(client) -> None:
    from app.agents.base_graph import _make_call_llm_node

    tid = _new_task(client)
    assert client.post(f"/api/tasks/{tid}/stop").json()["ok"] is True
    assert _flag(tid)
    node = _make_call_llm_node(
        "architect", "claude-opus-4-8", [], 60_000, task_id=str(tid)
    )
    state = {
        "messages": [{"role": "user", "content": "x"}],
        "verification": {},
        "result": {},
        "turns": 0,
        "submitted": False,
        "requires_human_approval": False,
        "tokens_in": 0,
        "tokens_out": 0,
    }
    out = node(state)
    assert out == {"submitted": True, "status": "stopped"}  # no LLM call was made
    get_activity_registry().remove(str(tid))


def test_resume_clears_the_flag_and_injects_the_message(client) -> None:
    tid = _new_task(client, "planning")
    client.post(f"/api/tasks/{tid}/stop")
    r = client.post(f"/api/tasks/{tid}/resume", json={"message": "continue please"})
    assert r.status_code == 200 and not _flag(tid)
    payload = get_activity_registry().get(str(tid)).pop_resume()
    assert payload and payload["message"] == "continue please"
    get_activity_registry().remove(str(tid))


def test_cancel_is_terminal_and_resume_is_refused(client) -> None:
    tid = _new_task(client, "planning")
    body = client.post(f"/api/tasks/{tid}/cancel").json()
    assert body["cancelled"] is True and _flag(tid)
    assert client.get(f"/api/tasks/{tid}").json()["status"] == "cancelled"
    assert (
        client.post(f"/api/tasks/{tid}/resume", json={"message": "x"}).status_code
        == 409
    )
    get_activity_registry().remove(str(tid))


def test_restart_after_stop_or_cancel_does_not_inherit_the_stale_abort(client) -> None:
    for how in ("stop", "cancel"):
        tid = _new_task(client, "blocked")
        client.post(f"/api/tasks/{tid}/{how}")
        assert _flag(tid)
        with patch("app.api.tasks.dispatch_job", new=AsyncMock()) as dj:
            r = client.post(f"/api/tasks/{tid}/restart")
        assert r.status_code == 200 and dj.await_count == 1, (how, r.text)
        assert not _flag(tid), f"restart after {how} kept the stale abort flag"
        get_activity_registry().remove(str(tid))


def test_run_after_a_stray_stop_on_an_idle_task_starts_clean(client) -> None:
    tid = _new_task(client, "pending")
    client.post(f"/api/tasks/{tid}/stop")  # nothing was running
    assert _flag(tid)
    with patch("app.api.tasks.dispatch_job", new=AsyncMock()):
        r = client.post(f"/api/tasks/{tid}/run", json={"mode": "full"})
    assert r.status_code == 200, r.text
    assert not _flag(tid)
    get_activity_registry().remove(str(tid))


def test_restart_is_refused_while_a_run_is_active(client) -> None:
    tid = _new_task(client, "coding")
    with patch("app.api.tasks.dispatch_job", new=AsyncMock()) as dj:
        r = client.post(f"/api/tasks/{tid}/restart")
    assert r.status_code == 409 and dj.await_count == 0


def test_stop_during_a_run_still_halts_later_stages() -> None:
    """The flag must persist for the rest of the CURRENT run — only entry
    points (run/restart/approve) clear it, not each agent stage."""
    reg = get_activity_registry()
    reg.get_or_create("987654")
    reg.set_abort("987654")
    for _stage in ("pm", "architect", "decomposer"):
        assert reg.should_abort("987654")
    assert reg.clear_abort("987654") is True and reg.clear_abort("987654") is False
    reg.remove("987654")


def test_clear_abort_on_an_unknown_task_is_a_safe_no_op() -> None:
    assert get_activity_registry().clear_abort("no-such-task-1") is False
