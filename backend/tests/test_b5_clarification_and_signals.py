"""Verification batch B5 (#334/#335/#338/#339/#506) — clarification round trip on real Postgres over
real HTTP, and the chat frustration/repetition signal.

Defects proven before the fix:
* the near-repeat detector had no minimum length, so a second "yes"/"ok" (answers to two consecutive
  questions) scored Jaccard 1.0 and the model was told the user was frustrated;
* "recent user messages" were built from role == "user" alone, but the tool loop stores tool RESULTS
  as role="user" list-content messages — in any conversation that had used a tool the user repeating
  themselves was compared against tool output and never noticed.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.chat_agent import _human_user_messages
from app.agents.user_sentiment import detect_user_frustration
from app.config import get_settings
from app.db.models import DevTask, PendingApproval
from app.tools.agents.request_clarification import make_request_clarification_handler

pytestmark = pytest.mark.skipif(
    not get_settings().database_url, reason="requires a real DATABASE_URL"
)


# ---------------------------------------------------------------- frustration / repetition


@pytest.mark.parametrize("word", ["yes", "ok", "continue", "sure thing", "go ahead"])
def test_repeated_short_answers_are_not_frustration(word: str) -> None:
    assert detect_user_frustration(word, [word]).frustrated is False


def test_a_real_repeat_is_still_detected() -> None:
    msg = "please fix the login bug in the auth module"
    signal = detect_user_frustration(msg, ["something else entirely", msg])
    assert signal.frustrated and any(
        s.startswith("repeated_message") for s in signal.signals
    )


def test_human_user_messages_skips_tool_results() -> None:
    history = [
        {"role": "user", "content": "please fix the login bug in the auth module"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "t1", "name": "read_file"}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}],
        },
        {"role": "assistant", "content": "done"},
    ]
    assert _human_user_messages(history) == [
        "please fix the login bug in the auth module"
    ]
    # ...so the repeat is caught even though a tool round-trip sits in between
    assert detect_user_frustration(
        "please fix the login bug in the auth module", _human_user_messages(history)
    ).frustrated


# ---------------------------------------------------------------- clarification round trip


@asynccontextmanager
async def _session():
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            yield s
    finally:
        await engine.dispose()


def _run(coro):
    return asyncio.run(coro)


def _make_task(status: str = "blocked") -> int:
    async def go() -> int:
        async with _session() as s:
            t = DevTask(
                title="b5 clarify probe", description="build the thing", status=status
            )
            s.add(t)
            await s.commit()
            await s.refresh(t)
            return t.id

    return _run(go())


def _task_status(tid: int) -> str:
    async def go() -> str:
        async with _session() as s:
            return (await s.get(DevTask, tid)).status

    return _run(go())


def _rows(tid: int) -> list[tuple[str, str]]:
    async def go():
        async with _session() as s:
            r = (
                await s.execute(
                    select(PendingApproval).where(PendingApproval.task_id == tid)
                )
            ).scalars()
            return sorted((x.status, x.agent_name) for x in r)

    return _run(go())


def _drop(tid: int) -> None:
    async def go() -> None:
        async with _session() as s:
            await s.execute(
                delete(PendingApproval).where(PendingApproval.task_id == tid)
            )
            await s.execute(delete(DevTask).where(DevTask.id == tid))
            await s.commit()

    _run(go())


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def _ask(
    agent: str, tid: int, question: str = "Which database should the service use?"
) -> str:
    out = make_request_clarification_handler(agent, str(tid))({"question": question})
    assert out.startswith("Clarification request recorded")
    return f"clarify-{tid}-{agent}"


def test_planner_clarification_answer_resumes_planning_with_the_answer(client) -> None:
    tid = _make_task("blocked")
    try:
        thread = _ask("planner", tid)
        assert any(
            p["threadId"] == thread
            for p in client.get("/api/approvals/pending").json()["approvals"]
        )
        with patch("app.api.agents.launch_planner", new=AsyncMock()) as launch:
            r = client.post(
                f"/api/approvals/{thread}/approve", json={"answer": "Use Postgres 16"}
            )
        assert r.status_code == 200, r.text
        launch.assert_awaited_once()
        args = launch.await_args.args
        assert (
            args[0] == tid
            and "Use Postgres 16" in args[2]
            and "build the thing" in args[2]
        )
        assert _task_status(tid) == "planning"
    finally:
        _drop(tid)


def test_coder_clarification_answer_resumes_the_coder_not_the_planner(client) -> None:
    tid = _make_task("blocked")
    try:
        thread = _ask("coder", tid)
        with patch("app.api.agents.launch_coder", new=AsyncMock()) as coder, patch(
            "app.api.agents.launch_planner", new=AsyncMock()
        ) as planner:
            r = client.post(
                f"/api/approvals/{thread}/approve", json={"answer": "Use Postgres 16"}
            )
        assert r.status_code == 200, r.text
        planner.assert_not_awaited()
        coder.assert_awaited_once()
        assert "Use Postgres 16" in str(coder.await_args)
    finally:
        _drop(tid)


def test_rejecting_or_answering_nothing_does_not_resume_anything(client) -> None:
    for action, body in (("reject", None), ("approve", {})):
        tid = _make_task("blocked")
        try:
            thread = _ask("planner", tid)
            with patch("app.api.agents.launch_planner", new=AsyncMock()) as launch:
                r = client.post(f"/api/approvals/{thread}/{action}", json=body)
            assert r.status_code == 200
            launch.assert_not_awaited()
            assert _task_status(tid) == "blocked"
        finally:
            _drop(tid)


def test_a_second_question_after_the_first_answer_reaches_a_human_again(client) -> None:
    tid = _make_task("blocked")
    try:
        thread = _ask("planner", tid)
        with patch("app.api.agents.launch_planner", new=AsyncMock()):
            client.post(f"/api/approvals/{thread}/approve", json={"answer": "Postgres"})
        assert _task_status(tid) == "planning"
        # the resumed planner asks something else and the task is blocked again
        _run(_set_status(tid, "blocked"))
        thread2 = _ask("planner", tid, "Should the API be REST or GraphQL?")
        assert thread2 == thread
        pending = [
            p
            for p in client.get("/api/approvals/pending").json()["approvals"]
            if p["taskId"] == tid
        ]
        assert len(pending) == 1 and "REST or GraphQL" in str(pending[0])
        assert _rows(tid) == [("approved", "planner"), ("pending", "planner")]
        r = client.post(f"/api/approvals/{thread}/approve", json={"answer": "REST"})
        assert r.status_code == 200
        assert (
            client.post(
                f"/api/approvals/{thread}/approve", json={"answer": "REST"}
            ).status_code
            == 409
        )
    finally:
        _drop(tid)


async def _set_status(tid: int, status: str) -> None:
    async with _session() as s:
        t = await s.get(DevTask, tid)
        t.status = status
        await s.commit()
