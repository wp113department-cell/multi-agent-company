"""Verification batch B5 (#360) — chat context survives an app restart, on real Postgres over HTTP.

Defect proven before the fix: `get_or_restore_session` (which rebuilds a session from the
chat_messages table) was imported into app/api/chat.py with `# noqa: F401` and never called, so after
a restart every conversation answered 404 and its stored history could not be continued. The history
that would have been restored was also lossy (tool blocks came back as JSON strings) and could begin
on an orphaned tool_result / end on a tool_use with no result, which the API rejects.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import chat as chat_model
from app.models.chat import prepare_restored_history

pytestmark = pytest.mark.skipif(
    not get_settings().database_url, reason="requires a real DATABASE_URL"
)

TOOL_USE = [
    {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.py"}}
]
TOOL_RESULT = [{"type": "tool_result", "tool_use_id": "t1", "content": "print(1)"}]


def _row(role, content):
    return {
        "role": role,
        "content": content if isinstance(content, str) else json.dumps(content),
    }


def test_restored_history_round_trips_tool_blocks() -> None:
    rows = [
        _row("user", "fix the bug"),
        _row("assistant", TOOL_USE),
        _row("user", TOOL_RESULT),
        _row("assistant", "done, it was the import"),
    ]
    history = prepare_restored_history(rows)
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
    assert history[1]["content"] == TOOL_USE and history[2]["content"] == TOOL_RESULT


def test_a_window_cut_mid_tool_round_trip_is_repaired() -> None:
    rows = [  # the LIMIT started in the middle of a round trip and the last turn died mid-flight
        _row("user", TOOL_RESULT),
        _row("assistant", "ok"),
        _row("user", "next thing"),
        _row("assistant", "on it"),
        _row("user", "and then?"),
        _row("assistant", TOOL_USE),
    ]
    history = prepare_restored_history(rows)
    assert history[0] == {"role": "user", "content": "next thing"}
    assert history[-1] == {"role": "assistant", "content": "on it"}


def test_a_user_message_that_looks_like_json_stays_text() -> None:
    history = prepare_restored_history(
        [_row("user", '[{"type": "widget"}]'), _row("assistant", "that is a JSON list")]
    )
    assert history[0]["content"] == '[{"type": "widget"}]'


@asynccontextmanager
async def _db():
    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            yield s
    finally:
        await engine.dispose()


def _seed(sid: str, rows: list[dict]) -> None:
    async def go() -> None:
        async with _db() as db:
            for i, r in enumerate(rows):
                await db.execute(
                    text(
                        "INSERT INTO chat_messages (session_id, repo_path, role, content, created_at) "
                        "VALUES (:s, '/tmp/b5repo', :r, :c, now() + (:i || ' seconds')::interval)"
                    ),
                    {"s": sid, "r": r["role"], "c": r["content"], "i": str(i)},
                )
            await db.commit()

    asyncio.run(go())


def _drop(sid: str) -> None:
    async def go() -> None:
        async with _db() as db:
            await db.execute(
                text("DELETE FROM chat_messages WHERE session_id = :s"), {"s": sid}
            )
            await db.commit()

    asyncio.run(go())


def test_a_session_lost_to_a_restart_is_restored_and_can_take_the_next_message() -> (
    None
):
    from app.agents.chat_agent import ChatAgent
    from app.main import app

    sid = str(uuid.uuid4())
    _seed(
        sid,
        [
            _row("user", "fix the bug"),
            _row("assistant", TOOL_USE),
            _row("user", TOOL_RESULT),
            _row("assistant", "done, it was the import"),
        ],
    )
    seen: dict = {}

    async def fake_run(self, user_message: str) -> None:
        seen["history"] = list(self.session.history)
        seen["repo"] = self.session.repo_path
        await self.session.push({"type": "done"})

    try:
        chat_model._sessions.pop(sid, None)  # what a restart does
        with TestClient(app) as c, patch.object(ChatAgent, "run", fake_run):
            r = c.post(
                f"/api/chat/sessions/{sid}/messages",
                json={"message": "and now add a test"},
            )
            assert r.status_code == 200, r.text
        assert seen["repo"] == "/tmp/b5repo"
        assert [m["role"] for m in seen["history"]] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        assert seen["history"][1]["content"] == TOOL_USE
    finally:
        chat_model._sessions.pop(sid, None)
        _drop(sid)


def test_an_unknown_session_is_still_404() -> None:
    from app.main import app

    with TestClient(app) as c:
        r = c.post(
            f"/api/chat/sessions/{uuid.uuid4()}/messages", json={"message": "hi"}
        )
    assert r.status_code == 404
